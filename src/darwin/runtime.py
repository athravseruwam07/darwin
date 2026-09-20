"""One runtime/controller/model for simulation and hardware.

Only the environment/actuator and camera adapters differ. Operator jobs are serialized,
STOP cancels by generation, and a separate monitor enforces freshness/lease while jobs
fit or wait. No browser or learner can command physical outputs directly.
"""
from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
import copy
import json
import math
import threading
import time
import uuid
import cv2
import numpy as np
from darwin.config import Config
from darwin.types import Frame, Pose, RequestedAction
from darwin.episodes import transition
from darwin.safety import SafetySupervisor, SafetyViolation

ROOT=Path(__file__).resolve().parents[2]

class Runtime:
    def __init__(self, config: Config | None=None, *, realtime=True, run_root=None):
        from darwin.learning.model import MotionModel
        from darwin.control.policy import Policy
        from darwin.recording.writer import RunWriter
        from darwin.vision.calibration import Calibration
        from darwin.vision.tracking import Tracker
        self.config=config or Config()
        if self.config.mode=='replay': raise ValueError('use read-only ReplayRuntime')
        self.realtime=realtime; self.lock=threading.RLock(); self.closed=False
        self.safety=SafetySupervisor(self.config)
        self.state='DISARMED'; self.stop_reason='awaiting operator start'; self.busy=False
        self.model=MotionModel(ridge_lambda=self.config.ridge_lambda)
        self.frozen_model=None; self.model_ready=False
        self.policy=Policy(self.config)
        self.pose=None; self.target=None; self.trail=[]; self.predicted_motion=[]
        self.metrics={}; self.events=[]; self.recovery_phase='initial calibration required'
        self.samples=[]; self.heldout=[]; self.rejected=[]; self.latest_residual=None
        self.frame=None; self.frame_seq=0; self.last_receipt=None
        self.faults={}; self._job=None; self._job_error=None; self._job_result=None
        self._cancel=threading.Event(); self._audit_index=0; self._monitor_error=None
        self._pose_history=[]
        self.camera=None; self.env=None; self.transport=None; self.actuator=None
        self._hardware_connected=False; self._last_snapshot_log=0.
        self.calibration=Calibration.from_corners(
            [(0,0),(self.config.camera_width-1,0),(self.config.camera_width-1,self.config.camera_height-1),(0,self.config.camera_height-1)],
            self.config.arena_width_m,self.config.arena_height_m,
            (self.config.camera_width,self.config.camera_height),camera_id='simulation',
            heading_offset_rad=self.config.heading_offset_rad)
        if self.config.mode=='hardware':
            self.calibration=None
            if self.config.calibration_path:
                self.calibration=Calibration.load(self.config.calibration_path)
                if not math.isclose(self.calibration.width_m,self.config.arena_width_m) or not math.isclose(self.calibration.height_m,self.config.arena_height_m):
                    raise ValueError('saved calibration dimensions differ from configured arena')
                if tuple(self.calibration.image_size)!=(self.config.camera_width,self.config.camera_height):
                    raise ValueError('saved calibration resolution differs from camera config')
        self._render_calibration=self.calibration
        self.tracker=Tracker(marker_id=self.config.marker_id,heading_offset_rad=0)
        if self.config.mode=='simulation':
            from darwin.simulation.environment import SimulationEnvironment
            self.env=SimulationEnvironment(self.config)
            self.actuator=self.env
        self.writer=RunWriter(run_root or ROOT/'data/runs',metadata={
            'mode':self.config.mode,'software_version':'0.1.0','config_id':self.config.config_id,
            'seed':self.config.seed,'observation':self.config.observation,
            'timebase':'synthetic monotonic seconds' if self.env else 'host monotonic seconds',
            'measurement_version':'pulse_plus_settle_v1','units':'meters, seconds, radians; x right, y up, CCW',
            'hardware_verified':False},config=self.config.public())
        if self.calibration and hasattr(self.writer,'save_artifact'):
            self.writer.save_artifact('calibration.json',self.calibration.to_dict())
        self.run_id=self.writer.run_id
        self._observe(log=True)
        self._event('runtime_started',{'mode':self.config.mode})
        self._monitor=threading.Thread(target=self._monitor_loop,name='darwin-safety',daemon=True)
        self._monitor.start()

    @property
    def now(self): return self.env.now if self.env is not None else time.monotonic()

    def _event(self, kind, payload=None):
        event={'kind':kind,'at':self.now,'wall_monotonic':time.monotonic(),**(payload or {})}
        self.events.append(event); self.events=self.events[-100:]
        self.writer.append('events',event)

    def _observe(self, log=False):
        with self.lock:
            if self.config.mode=='simulation':
                if self.faults.get('stale_frames') and self.pose is not None: return self.pose
                if self.config.observation=='vision':
                    from darwin.vision.markers import render_frame
                    self.frame_seq+=1
                    x,y,theta=self.env.truth_for_renderer()
                    self.frame=render_frame(x,y,theta,self._render_calibration,self.frame_seq,self.now,hide=self.faults.get('hide_marker',False),marker_id=self.config.marker_id)
                    self.pose=self.tracker.observe(self.frame,self.calibration)
                else:
                    self.pose=self.env.observe()
                    if self.faults.get('hide_marker'):
                        self.pose=replace(self.pose,valid=False,invalid_reason='marker hidden')
            elif self.camera is not None:
                frame=self.camera.latest_frame()
                if frame is not None:
                    self.frame=frame
                    if self.calibration:
                        self.pose=self.tracker.observe(frame,self.calibration)
                    else:
                        self.pose=Pose(frame.id,frame.captured_at or frame.received_at,0,0,0,False,0,'uncalibrated','calibration required')
            if self.pose and (not self._pose_history or self._pose_history[-1].frame_id!=self.pose.frame_id):
                self._pose_history.append(self.pose); self._pose_history=self._pose_history[-100:]
            if self.pose and log:
                self.writer.append('observations',asdict(self.pose))
                if self.frame:
                    self.writer.append('frames',{'id':self.frame.id,'captured_at':self.frame.captured_at,'received_at':self.frame.received_at,'source':self.frame.source,'timestamp_quality':self.frame.timestamp_quality})
            return self.pose

    def _healthy(self):
        if self.faults.get('disconnect_serial') or self.faults.get('invalid_ack'): return False
        if self.config.mode=='simulation': return True
        return bool(self._hardware_connected and self.transport and self.transport.health.get('connected') and not self.transport.health.get('error'))

    def _set_state(self,generation,state):
        with self.lock:
            self.safety.assert_current(generation)
            self.state=state

    def _wait_stationary(self,generation):
        if self.env: return
        deadline=time.monotonic()+2.
        while time.monotonic()<deadline:
            self._observe(); self._check(generation)
            recent=[p for p in self._pose_history if p.valid and self.now-p.observed_at<=self.config.stationary_window_s+.1]
            if len(recent)>=3 and recent[-1].observed_at-recent[0].observed_at>=self.config.stationary_window_s:
                origin=recent[-1]
                if all(math.hypot(p.x_m-origin.x_m,p.y_m-origin.y_m)<=self.config.stationary_position_tolerance_m and abs(math.atan2(math.sin(p.theta_rad-origin.theta_rad),math.cos(p.theta_rad-origin.theta_rad)))<=self.config.stationary_yaw_tolerance_rad for p in recent): return
            self._cancel.wait(.01)
        raise SafetyViolation('robot has not measurably settled')

    def _check(self, generation, exploration=False):
        if self.faults.get('stale_frames'): raise SafetyViolation('stale frame')
        if self.faults.get('queue_backlog'): raise SafetyViolation('command queue backlog')
        self.safety.check(self.pose,self.now,generation,transport_healthy=self._healthy(),exploration=exploration)

    def _hardware_check(self):
        try: self._check(self.safety.generation,exploration=self.state in {'PROBING','RECOVERING'})
        except Exception as exc: return str(exc)
        return None

    def _monitor_loop(self):
        while not self.closed:
            try:
                if self.config.mode=='hardware':
                    if self.transport and hasattr(self.transport,'poll_health'): self.transport.poll_health()
                    self._observe()
                if self.safety.active:
                    with self.lock:
                        self._check(self.safety.generation,exploration=self.state in {'PROBING','RECOVERING'})
                if time.monotonic()-self._last_snapshot_log>.25:
                    self.writer.append('snapshots',self.snapshot())
                    self._last_snapshot_log=time.monotonic()
            except Exception as exc:
                self._monitor_error=str(exc)
                if self.safety.active: self._stop(str(exc),fault=True)
            time.sleep(.02)

    def _stop(self, reason='operator stop', fault=False):
        # Invalidate pending action before waiting on transport. Do not wait on job.
        self.safety.stop(reason); self._cancel.set()
        if self.actuator is not None:
            try: self.actuator.stop()
            except Exception: pass
        with self.lock:
            self.state='FAULT' if fault else 'DISARMED'; self.stop_reason=reason
            self.predicted_motion=[]
        try:
            self._event('stop',{'reason':reason,'fault':fault}); self.writer.flush()
        except Exception as exc: self._monitor_error=str(exc)

    def _drain_audit(self):
        audits=getattr(self.actuator,'audit_records',[])
        for entry in audits[self._audit_index:]: self.writer.append('actuator_audit',entry)
        self._audit_index=len(audits)

    def _pulse(self, action, generation, exploration=False):
        self._wait_stationary(generation)
        start=self._observe(log=True)
        self._check(generation,exploration)
        self.writer.append('actions',asdict(action))
        self.safety.assert_current(generation)
        if self.env:
            with self.lock:
                self.safety.assert_current(generation)
                receipt=self.actuator.execute(action)
                self._observe()
        else:
            receipt=self.actuator.execute(action)
        self.last_receipt=receipt
        self.writer.append('events',{'kind':'actuation_receipt',**asdict(receipt)})
        self._drain_audit()
        if not receipt.accepted: raise SafetyViolation(receipt.error or 'actuation rejected')
        end=self._observe(log=True)
        reason=None if generation==self.safety.generation else 'action crossed stop/reset/scramble'
        uncertainty=0. if self.env else max(0.,((receipt.ack_at or receipt.sent_at)-receipt.sent_at)*1000)+(self.config.timestamp_bound_ms or 0.)
        sample=transition(action,start,end,self.config.config_id,uncertainty,reason,expected_elapsed_s=(self.config.pulse_ms+self.config.settle_ms)/1000)
        self.writer.append('transitions',asdict(sample))
        self.safety.assert_current(generation)
        self.safety.actions+=1
        if not sample.valid:
            self.rejected.append(sample)
            raise SafetyViolation(sample.rejection_reason)
        self.trail.append({'x_m':end.x_m,'y_m':end.y_m}); self.trail=self.trail[-500:]
        if self.model_ready:
            predicted=self.model.predict([action.u])[0]
            self.latest_residual={'v_mps':sample.v_mps-float(predicted[0]),'omega_radps':sample.omega_radps-float(predicted[1])}
        self._check(generation,exploration)
        if self.realtime and self.env:
            self._cancel.wait((self.config.pulse_ms+self.config.settle_ms)/1000)
            self.safety.assert_current(generation)
        return sample

    def _learn(self, generation, recovery=False):
        from darwin.control.exploration import probe_actions
        from darwin.learning.model import MotionModel, evaluate
        self._set_state(generation,'RECOVERING' if recovery else 'PROBING')
        self.recovery_phase='collecting fresh probes' if recovery else 'initial probes'
        episode=uuid.uuid4().hex
        training=[]; heldout=[]
        for role,count,seed in [('train',self.config.initial_trials,self.config.seed+len(self.events)),('heldout',self.config.validation_trials,self.config.seed+10007+len(self.events))]:
            for action in probe_actions(seed,count,self.config.pulse_ms,episode+':'+role):
                sample=self._pulse(action,generation,exploration=True)
                (training if role=='train' else heldout).append(sample)
                if role=='train': self.samples.append(sample)
                else: self.heldout.append(sample)
        self.actuator.stop(); self._set_state(generation,'FITTING')
        model=MotionModel(ridge_lambda=self.config.ridge_lambda)
        fit=model.fit(training)
        self.safety.assert_current(generation)
        current=evaluate(model,heldout)
        baseline=np.sqrt(np.mean(np.array([[t.v_mps,t.omega_radps] for t in heldout])**2,axis=0))
        current['zero_baseline_v_rmse_mps']=float(baseline[0]); current['zero_baseline_omega_rmse_radps']=float(baseline[1])
        if baseline[0]<.002 or baseline[1]<.02 or current['v_rmse_mps']>baseline[0]*.7 or current['omega_rmse_radps']>baseline[1]*.7:
            raise SafetyViolation('insufficient predictable motion above stationary baseline')
        if current['v_rmse_mps']>.04 or current['omega_rmse_radps']>.4:
            raise SafetyViolation('held-out model errors exceed navigation gate')
        with self.lock:
            self.safety.assert_current(generation)
            self.model=model; self.model_ready=True
            self.metrics['current']=current
            self.metrics['fit']=fit
            if recovery and self.frozen_model is not None:
                self.metrics['frozen']=evaluate(self.frozen_model,heldout)
                self.metrics['adapted']=current
            else: self.metrics['before']=current
            ckpt=Path(self.writer.path)/'checkpoints'; ckpt.mkdir(exist_ok=True)
            model.save(ckpt/(model.model_id+'.json'))
            self._event('evaluation',{'metrics':self.metrics,'training_action_ids':[s.action_id for s in training], 'heldout_action_ids':[s.action_id for s in heldout]})
            self.recovery_phase='adapted model validated' if recovery else 'model validated'
            self.state='READY'; self.stop_reason=None
        return {'model_id':model.model_id,'metrics':self.metrics}

    def _navigate(self,generation):
        self._set_state(generation,'NAVIGATING'); target=self.target
        started=self.now; count=0
        while True:
            pose=self._observe()
            self._check(generation)
            distance=math.hypot(target[0]-pose.x_m,target[1]-pose.y_m)
            if distance<=self.config.goal_radius_m:
                self.actuator.stop()
                # Dwell is observed stationary time, not a single proximity frame.
                for _ in range(max(2,math.ceil(self.config.goal_dwell_ms/50))):
                    self.safety.assert_current(generation)
                    if self.env:
                        self.env.advance(.05)
                        if self.realtime: self._cancel.wait(.05)
                    else: self._cancel.wait(.05)
                    pose=self._observe(log=True); self._check(generation)
                    if math.hypot(target[0]-pose.x_m,target[1]-pose.y_m)>self.config.goal_radius_m: break
                else:
                    with self.lock:
                        self.safety.assert_current(generation)
                        self.state='GOAL'; self.stop_reason=None
                    result={'success':True,'final_distance_m':math.hypot(target[0]-pose.x_m,target[1]-pose.y_m),'actions':count,'elapsed_s':self.now-started,'target':target}
                    self._event('navigation_result',result); return result
                continue
            action=self.policy.choose(pose,target,self.model,{'bounds':self.config.safe_bounds})
            if action is None: raise SafetyViolation('no safe useful learned action')
            action=replace(action,episode_id='navigation:'+str(generation))
            pred=self.model.predict([action.u])[0]
            dt=(self.config.pulse_ms+self.config.settle_ms)/1000
            theta=pose.theta_rad+float(pred[1])*dt/2
            self.predicted_motion=[{'x_m':pose.x_m,'y_m':pose.y_m},{'x_m':pose.x_m+float(pred[0])*dt*math.cos(theta),'y_m':pose.y_m+float(pred[0])*dt*math.sin(theta)}]
            self._pulse(action,generation); count+=1

    def _run_job(self,name,generation):
        try:
            self._job_result=self._navigate(generation) if name=='navigate' else self._learn(generation,name=='recover')
            self.safety.assert_current(generation)
            self.safety.active=False; self.safety.latched=True
            self.actuator.stop(); self.writer.flush()
        except Exception as exc:
            self._job_error=str(exc)
            if generation==self.safety.generation: self._stop(str(exc),fault=True)
            if name=='navigate':
                d=None if self.pose is None else math.hypot(self.target[0]-self.pose.x_m,self.target[1]-self.pose.y_m)
                self._job_result={'success':False,'final_distance_m':d,'actions':self.safety.actions,'reason':str(exc)}
                try: self._event('navigation_result',self._job_result)
                except Exception: pass
        finally:
            self.busy=False

    def command(self,name,payload=None):
        payload=payload or {}
        name=name.replace('_','-')
        if name=='stop': self._stop(); return {'ok':True,'state':self.state}
        if name=='heartbeat': return {'ok':self.safety.heartbeat(payload.get('owner_id'))}
        with self.lock:
            if self.closed: raise ValueError('runtime closed')
            if name in {'start-calibration','recover','navigate'}:
                if self.busy: raise ValueError('another episode is active')
                if self.config.mode=='hardware' and not self._hardware_connected: raise ValueError('connect hardware explicitly first')
                if name=='navigate' and (not self.model_ready or self.target is None): raise ValueError('validated model and target required')
                if name=='recover' and self.frozen_model is None: raise ValueError('scramble a trained model first')
                self._observe()
                gen=self.safety.start(payload.get('owner_id'),self.now)
                try: self._check(gen,exploration=name!='navigate')
                except Exception:
                    self.safety.stop('start safety gate rejected'); raise
                self.busy=True; self.stop_reason=None; self._cancel.clear(); self._job_error=None; self._job_result=None
                self._job=threading.Thread(target=self._run_job,args=(name,gen),daemon=True,name='darwin-episode')
                self._event('episode_started',{'operation':name,'owner_id':self.safety.owner})
                self._job.start()
                return {'ok':True,'job':name,'generation':gen}
            if name=='target':
                if self.busy: raise ValueError('stop before changing target')
                target=payload.get('target') or [payload.get('x_m'),payload.get('y_m')]
                x,y=map(float,target)
                l,r,b,t=self.config.safe_bounds
                if not math.isfinite(x+y) or not l<=x<=r or not b<=y<=t: raise ValueError('target outside safe arena')
                self.target=(x,y); self._event('target',{'target':self.target}); return {'ok':True,'target':self.target}
            if name in {'scramble','reset-model','reset','calibration','connect','recenter'} and self.busy:
                raise ValueError('stop and wait for active pulse before changing state')
            if name=='scramble':
                if not self.model_ready: raise ValueError('learn a model before scramble')
                self._stop('scramble')
                self.frozen_model=copy.deepcopy(self.model)
                self.actuator.scramble(payload.get('mapping'))
                self._drain_audit()
                self.model_ready=False; self.samples=[]; self.heldout=[]; self.latest_residual=None
                self.recovery_phase='scrambled; recover with fresh observations'
                self._event('scramble',{'model_frozen':self.frozen_model.model_id})
                return {'ok':True}
            if name in {'reset-model','reset'}:
                from darwin.learning.model import MotionModel
                self._stop('model reset'); self.model=MotionModel(ridge_lambda=self.config.ridge_lambda)
                self.model_ready=False; self.frozen_model=None; self.samples=[]; self.heldout=[]; self.metrics={}; self.latest_residual=None
                self.recovery_phase='initial calibration required'; self._event('model_reset'); return {'ok':True}
            if name=='recenter':
                if not self.env: raise ValueError('hardware must be manually repositioned')
                self._stop('explicit simulated manual recenter')
                self.env.reset_pose(float(payload.get('x_m',.5)),float(payload.get('y_m',.5)),float(payload.get('theta_rad',0)))
                self.trail=[]; self._observe(log=True); self._event('intervention',{'type':'manual_recenter','pose':asdict(self.pose)}); return {'ok':True}
            if name=='fault':
                fault=payload.get('name'); fault={'disconnect':'disconnect_serial'}.get(fault,fault); enabled=payload.get('enabled',True)
                if fault not in {'hide_marker','stale_frames','disconnect_serial','invalid_ack','queue_backlog','boundary'}: raise ValueError('unknown diagnostic fault')
                if self.config.mode!='simulation': raise ValueError('fault injection is simulation only')
                if not isinstance(enabled,bool): raise ValueError('enabled must be boolean')
                self.faults[fault]=enabled
                if fault=='boundary' and enabled:
                    self.env.reset_pose(.12,.5,0); self._event('intervention',{'type':'boundary fault injection'})
                self._observe(log=True)
                if enabled: self._stop('diagnostic fault: '+fault,fault=True)
                self._event('fault_injection',payload); return {'ok':True}
            if name=='calibration':
                from darwin.vision.calibration import Calibration
                points=payload.get('points_px',payload.get('corners_px',payload.get('points')))
                width=float(payload.get('width_m',self.config.arena_width_m)); height=float(payload.get('height_m',self.config.arena_height_m))
                if width!=self.config.arena_width_m or height!=self.config.arena_height_m:
                    raise ValueError('arena dimensions must match config; restart with measured config')
                self.calibration=Calibration.from_corners(points,width,height,(self.config.camera_width,self.config.camera_height),camera_id=payload.get('camera_id',self.config.camera_backend),heading_offset_rad=float(payload.get('heading_offset_rad',0)),marker_height_m=float(payload.get('marker_height_m',0)))
                self.model_ready=False; self.frozen_model=None; self.samples=[]; self.heldout=[]; self.metrics={}; self.latest_residual=None; self._stop('calibration changed; relearn required')
                self.calibration.save(ROOT/'data'/('calibration-'+self.calibration.calibration_id+'.json'))
                self._observe(log=True); self._event('calibration',self.calibration.to_dict()); return {'ok':True,'calibration':self.calibration.to_dict()}
            if name=='connect':
                requested=payload.get('mode',self.config.mode)
                if requested!=self.config.mode: raise ValueError('mode changes require a new explicit process')
                self._stop('connected disarmed')
                if self.config.mode=='hardware': self._connect_hardware()
                self._observe(log=True); return {'ok':True,'state':'DISARMED'}
            if name=='export':
                from darwin.recording.export import export_run
                self.writer.flush()
                path=export_run(self.writer.path,ROOT/'reports'/'exports')
                self._event('export',{'path':str(path)}); return {'ok':True,'path':str(path)}
            raise ValueError('unknown command: '+name)

    def _connect_hardware(self):
        from darwin.io.camera import make_camera
        from darwin.io.serial_link import SerialTransport
        from darwin.io.actuator import HardwareActuator
        if not self.config.serial_port: raise ValueError('explicit identified serial port required')
        if self.transport: self.transport.close()
        if self.camera: self.camera.close()
        from darwin.learning.model import MotionModel
        self.model=MotionModel(self.config.ridge_lambda); self.model_ready=False; self.frozen_model=None
        self.samples=[]; self.heldout=[]; self.metrics={}; self.pose=None; self.frame=None; self._pose_history=[]
        self.last_receipt=None; self._audit_index=0; self.recovery_phase='reconnect requires fresh calibration trials'
        self.transport=SerialTransport(self.config.serial_port,self.config.baudrate,self.config.ack_timeout_ms)
        try:
            self.transport.connect(); self.transport.handshake(); self.transport.stop()
            self.camera=make_camera(self.config); self.camera.start()
            self.actuator=HardwareActuator(self.transport,self.config,safety_check=self._hardware_check)
            self._hardware_connected=True
        except Exception:
            if self.camera: self.camera.close()
            self.transport.close(); self._hardware_connected=False; raise

    def public_config(self): return self.config.public()

    def list_runs(self):
        return [{'run_id':p.name,'path':str(p)} for p in sorted(Path(self.writer.path).parent.iterdir(),reverse=True) if p.is_dir() and (p/'metadata.json').exists()][:100]

    def snapshot(self):
        pose=asdict(self.pose) if self.pose else None
        age=max(0,(self.now-self.pose.observed_at)*1000) if self.pose else None
        if self.faults.get('stale_frames'): age=max(age or 0,self.config.max_frame_age_ms+1)
        return {'mode':self.config.mode,'state':self.state,'stop_reason':self.stop_reason,'run_id':self.run_id,
            'pose':pose,'target':self.target,'trail':self.trail[-500:],'predicted_motion':self.predicted_motion,
            'transport_health':'healthy' if self._healthy() else 'disconnected','frame_age_ms':age,
            'ack_age_ms':max(0,(self.now-self.last_receipt.ack_at)*1000) if self.last_receipt and self.last_receipt.ack_at is not None else None,
            'valid_sample_count':len(self.samples),'rejected_sample_count':len(self.rejected),'heldout_sample_count':len(self.heldout),
            'model_id':self.model.model_id if self.model_ready else None,'validation_metrics':self.metrics,
            'recovery_phase':self.recovery_phase,'busy':self.busy,'owner_id':self.safety.owner if self.safety.active else None,
            'calibration':self.calibration.to_dict() if self.calibration else None,'events':self.events[-25:],
            'latest_residual':self.latest_residual,'faults':dict(self.faults),'model_ready':self.model_ready,
            'observation_mode':self.config.observation if self.env else self.config.camera_backend,
            'actions':self.safety.actions,'error':self._job_error or self._monitor_error}

    def latest_jpeg(self):
        if self.frame is None: return None
        ok,buffer=cv2.imencode('.jpg',self.frame.image_bgr)
        return buffer.tobytes() if ok else None

    def wait(self, timeout=60, owner='cli'):
        deadline=time.monotonic()+timeout
        while self.busy and time.monotonic()<deadline:
            self.safety.heartbeat(owner)
            time.sleep(.01)
        if self.busy: self._stop('job wait timeout',fault=True); raise TimeoutError('episode deadline')
        if self._job_error: raise RuntimeError(self._job_error)
        return self._job_result

    def close(self):
        if self.closed: return
        self._stop('runtime closed'); self.closed=True
        if self._job: self._job.join(timeout=2)
        self._monitor.join(timeout=2)
        if self.camera: self.camera.close()
        if self.transport: self.transport.close()
        self.writer.append('snapshots',self.snapshot())
        self.writer.close()
