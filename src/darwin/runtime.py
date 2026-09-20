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
from darwin.types import Frame, Pose
from darwin.episodes import transition
from darwin.safety import SafetySupervisor, SafetyViolation

ROOT=Path(__file__).resolve().parents[2]


def stationary_suffix_span(poses, *, position_tolerance_m, yaw_tolerance_rad,
                           max_frame_gap_s=.15):
    """Measure the newest uninterrupted stationary span in camera time."""
    valid = [pose for pose in poses if pose.valid]
    if len(valid) < 3:
        return 0.0
    latest = valid[-1]
    stable = [latest]
    newer = latest
    for pose in reversed(valid[:-1]):
        if pose.frame_id == newer.frame_id:
            continue
        gap = newer.observed_at - pose.observed_at
        if pose.frame_id >= newer.frame_id or gap <= 0 or gap > max_frame_gap_s:
            break
        position_delta = math.hypot(pose.x_m-latest.x_m, pose.y_m-latest.y_m)
        yaw_delta = abs(math.atan2(math.sin(pose.theta_rad-latest.theta_rad),
                                   math.cos(pose.theta_rad-latest.theta_rad)))
        if position_delta > position_tolerance_m or yaw_delta > yaw_tolerance_rad:
            break
        stable.append(pose)
        newer = pose
    return latest.observed_at-stable[-1].observed_at if len(stable) >= 3 else 0.0

class Runtime:
    def __init__(self, config: Config | None=None, *, realtime=True, run_root=None):
        from darwin.learning.model import MotionModel
        from darwin.learning.change_detection import ResidualChangeDetector
        from darwin.learning.model_memory import BodyModelMemory
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
        self.pose=None; self.target=None; self.route=[]; self.route_index=None
        self.trail=[]; self.predicted_motion=[]
        self.metrics={}; self.events=[]; self.recovery_phase='initial calibration required'
        self.samples=[]; self.heldout=[]; self.rejected=[]; self.latest_residual=None
        self.latest_prediction_comparison=None
        self.change_detector=ResidualChangeDetector(threshold=self.config.mismatch_threshold,
            required_exceedances=self.config.mismatch_required_exceedances)
        self.change_detection=self.change_detector.status().to_dict(); self.change_detected=False; self._change_recovered=False
        self.body_change_signal=None
        self.model_memory=BodyModelMemory(); self.matched_model_id=None
        self.model_uncertainty=None; self.frozen_predicted_motion=[]; self.adapted_predicted_motion=[]
        self.obstacles=[]; self._last_obstacle_frame=None
        self.boundary_recovery_active=False
        self.obstacle_detector=None
        if self.config.obstacle_detection_enabled:
            from darwin.vision.obstacles import ObstacleDetector
            self.obstacle_detector=ObstacleDetector(robot_marker_id=self.config.marker_id)
        self.frame=None; self.frame_seq=0; self.last_receipt=None
        self.faults={}; self._job=None; self._job_error=None; self._job_result=None
        self._cancel=threading.Event(); self._audit_index=0; self._monitor_error=None
        self._pending_mutations=[]
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
            if (self.obstacle_detector and self.frame and self.calibration and
                    self.frame.id!=self._last_obstacle_frame and self.frame.id%3==0):
                detected=self.obstacle_detector.detect(self.frame,self.calibration)
                self.obstacles=[]
                for obstacle in detected:
                    item=obstacle.to_dict()
                    item.update(x_m=item['center_m'][0],y_m=item['center_m'][1],points=item['polygon_m'])
                    self.obstacles.append(item)
                self._last_obstacle_frame=self.frame.id
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
        # Each gate requires a fresh camera-time window. Host receive latency is
        # checked separately by SafetySupervisor and must not shorten this span.
        with self.lock:
            self._pose_history=[]
        deadline=time.monotonic()+2.
        span=0.
        max_gap=min(self.config.max_frame_age_ms/1000,
                    max(.12,4/self.config.camera_fps))
        while time.monotonic()<deadline:
            self._observe(); self._check(generation)
            span=stationary_suffix_span(self._pose_history,
                position_tolerance_m=self.config.stationary_position_tolerance_m,
                yaw_tolerance_rad=self.config.stationary_yaw_tolerance_rad,
                max_frame_gap_s=max_gap)
            if span>=self.config.stationary_window_s:
                return
            self._cancel.wait(.01)
        self._event('stationary_timeout',{'observed_stationary_span_s':span,
            'required_stationary_span_s':self.config.stationary_window_s,
            'position_tolerance_m':self.config.stationary_position_tolerance_m,
            'yaw_tolerance_rad':self.config.stationary_yaw_tolerance_rad,
            'frame_count':len(self._pose_history),'max_frame_gap_s':max_gap})
        raise SafetyViolation('robot has not measurably settled')

    def _check(self, generation, exploration=False, allow_boundary_recovery=None):
        if self.faults.get('stale_frames'): raise SafetyViolation('stale frame')
        if self.faults.get('queue_backlog'): raise SafetyViolation('command queue backlog')
        if allow_boundary_recovery is None:
            allow_boundary_recovery=(self.state=='NAVIGATING' and self.model_ready)
        self.safety.check(self.pose,self.now,generation,transport_healthy=self._healthy(),
            exploration=exploration,allow_boundary_recovery=allow_boundary_recovery)

    def _hardware_check(self):
        try: self._check(self.safety.generation,exploration=self.state in {'PROBING','RECOVERING'})
        except Exception as exc: return str(exc)
        return None

    def _monitor_loop(self):
        while not self.closed:
            monitored_generation=self.safety.generation if self.safety.active else None
            try:
                if self.config.mode=='hardware':
                    if self.transport and hasattr(self.transport,'poll_health'): self.transport.poll_health()
                    self._observe()
                if self.safety.active:
                    with self.lock:
                        monitored_generation=self.safety.generation
                        self._check(monitored_generation,exploration=self.state in {'PROBING','RECOVERING'})
                if time.monotonic()-self._last_snapshot_log>.25:
                    self.writer.append('snapshots',self.snapshot())
                    self._last_snapshot_log=time.monotonic()
            except Exception as exc:
                # An old monitor iteration must never cancel a newly started
                # episode after the generation changed on another thread.
                current_episode=(monitored_generation is not None and self.safety.active and
                                 self.safety.generation==monitored_generation)
                if monitored_generation is not None and not current_episode:
                    time.sleep(.02)
                    continue
                self._monitor_error=str(exc)
                if current_episode:
                    self._stop(str(exc),fault=True)
            time.sleep(.02)

    def _stop(self, reason='operator stop', fault=False):
        # Invalidate pending action before waiting on transport. Do not wait on job.
        self.safety.stop(reason); self._cancel.set()
        if self.actuator is not None:
            try: self.actuator.stop()
            except Exception: pass
        with self.lock:
            self._pending_mutations=[]
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
        self.safety.budget_actions+=1
        if not sample.valid:
            self.rejected.append(sample)
            raise SafetyViolation(sample.rejection_reason)
        self.trail.append({'x_m':end.x_m,'y_m':end.y_m}); self.trail=self.trail[-500:]
        if self.model_ready:
            predicted=self.model.predict([action.u])[0]
            self.latest_residual={'v_mps':sample.v_mps-float(predicted[0]),'omega_radps':sample.omega_radps-float(predicted[1])}
            self.latest_prediction_comparison={
                'command':{'left':float(action.u[0]),'right':float(action.u[1])},
                'expected':{'forward_mps':float(predicted[0]),'turn_radps':float(predicted[1])},
                'observed':{'forward_mps':float(sample.v_mps),'turn_radps':float(sample.omega_radps)},
            }
            if self.state=='NAVIGATING':
                normalized=(self.latest_residual['v_mps']/.08,self.latest_residual['omega_radps']/.7)
                status=self.change_detector.update(normalized)
                self.change_detection=status.to_dict()
                self.change_detected=self.change_detected or status.detected
        self._check(generation,exploration)
        if self.realtime and self.env:
            self._cancel.wait((self.config.pulse_ms+self.config.settle_ms)/1000)
            self.safety.assert_current(generation)
        return sample

    def _learn(self, generation, recovery=False):
        from darwin.control.exploration import probe_actions, recovery_probe_actions
        from darwin.learning.model import MotionModel, evaluate
        from darwin.learning.model_memory import ResponseSignature
        self.safety.begin_budget_window(self.now)
        self._set_state(generation,'RECOVERING' if recovery else 'PROBING')
        self.recovery_phase='collecting fresh probes' if recovery else 'initial probes'
        episode=uuid.uuid4().hex
        training=[]; heldout=[]
        roles=[('train',self.config.recovery_trials if recovery else self.config.initial_trials,self.config.seed+len(self.events)),
               ('heldout',self.config.recovery_validation_trials if recovery else self.config.validation_trials,self.config.seed+10007+len(self.events))]
        for role,count,seed in roles:
            actions = (recovery_probe_actions(seed,count,self.config.pulse_ms,episode+':'+role,
                       candidate_levels=self.config.candidate_levels,active=role=='train')
                       if recovery else probe_actions(seed,count,self.config.pulse_ms,episode+':'+role))
            for action in actions:
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
            checkpoint=ckpt/(model.model_id+'.json'); model.save(checkpoint)
            signature=ResponseSignature(tuple(float(value) for value in model.coefficients.ravel()))
            matched=self.model_memory.match(signature,max_distance=self.config.model_memory_match_distance)
            self.matched_model_id=matched.checkpoint_id if matched else None
            self.model_memory.add(signature,checkpoint_id=model.model_id,checkpoint_path=str(checkpoint),
                validation_metrics={'normalized_rmse':current['normalized_rmse'],'v_rmse_mps':current['v_rmse_mps'],
                                    'omega_rmse_radps':current['omega_rmse_radps']},validated=True)
            self.model_memory.save(Path(self.writer.path)/'model_memory.json')
            self.model_uncertainty=current['normalized_rmse']
            self._event('evaluation',{'metrics':self.metrics,'training_action_ids':[s.action_id for s in training], 'heldout_action_ids':[s.action_id for s in heldout]})
            self.recovery_phase='adapted model validated' if recovery else 'model validated'
            self.state='READY'; self.stop_reason=None
        return {'model_id':model.model_id,'metrics':self.metrics}

    def _navigate(self,generation):
        self.safety.begin_budget_window(self.now)
        self._set_state(generation,'NAVIGATING'); target=self.target
        started=self.now; count=0
        while True:
            with self.lock:
                pose=self._observe()
                self._check(generation)
                distance=math.hypot(target[0]-pose.x_m,target[1]-pose.y_m)
                mutation_waiting=bool(self._pending_mutations)
            operating=self.config.safe_bounds
            inside_operating=(operating[0]<=pose.x_m<=operating[1] and operating[2]<=pose.y_m<=operating[3])
            hysteresis=min(.002,self.config.boundary_margin_m/10)
            inside_recovered=(operating[0]+hysteresis<=pose.x_m<=operating[1]-hysteresis and
                              operating[2]+hysteresis<=pose.y_m<=operating[3]-hysteresis)
            if not self.boundary_recovery_active and not inside_operating:
                self.boundary_recovery_active=True
                self.recovery_phase='returning inward from green safety buffer'
                self._event('boundary_recovery_started',{'pose':asdict(pose),'target':target})
            elif self.boundary_recovery_active and inside_recovered:
                self.boundary_recovery_active=False
                self.recovery_phase='inside green operating boundary; target navigation resumed'
                self._event('boundary_recovered',{'pose':asdict(pose),'target':target})
            if mutation_waiting:
                self._apply_pending_mutations(generation)
                continue
            if distance<=self.config.goal_contact_radius_m and not self.boundary_recovery_active:
                self.actuator.stop()
                # Dwell is observed stationary time, not a single proximity frame.
                for _ in range(max(2,math.ceil(self.config.goal_dwell_ms/50))):
                    self.safety.assert_current(generation)
                    if self.env:
                        self.env.advance(.05)
                        if self.realtime: self._cancel.wait(.05)
                    else: self._cancel.wait(.05)
                    pose=self._observe(log=True); self._check(generation)
                    if math.hypot(target[0]-pose.x_m,target[1]-pose.y_m)>self.config.goal_contact_radius_m: break
                else:
                    with self.lock:
                        self.safety.assert_current(generation)
                        self.state='GOAL'; self.stop_reason=None
                    result={'success':True,'final_distance_m':math.hypot(target[0]-pose.x_m,target[1]-pose.y_m),'actions':count,'elapsed_s':self.now-started,'target':target}
                    self._event('navigation_result',result); return result
                continue
            recovery_target=(
                min(max(pose.x_m,operating[0]+hysteresis),operating[1]-hysteresis),
                min(max(pose.y_m,operating[2]+hysteresis),operating[3]-hysteresis),
            )
            objective=recovery_target if self.boundary_recovery_active else target
            action=self.policy.choose(pose,objective,self.model,{
                'bounds':self.config.boundary_recovery_bounds if self.boundary_recovery_active else operating,
                'recovery_bounds':operating if self.boundary_recovery_active else None,
                'physical_bounds':self.config.physical_bounds,
                'obstacles':[item for item in self.obstacles if item.get('confidence',0)>=.55],
                'obstacle_padding_m':.01})
            if action is None:
                reason='no safe inward recovery action' if self.boundary_recovery_active else 'no safe useful learned action'
                raise SafetyViolation(reason)
            action=replace(action,episode_id='navigation:'+str(generation))
            pred=self.model.predict([action.u])[0]
            dt=(self.config.pulse_ms+self.config.settle_ms)/1000
            theta=pose.theta_rad+float(pred[1])*dt/2
            self.predicted_motion=[{'x_m':pose.x_m,'y_m':pose.y_m},{'x_m':pose.x_m+float(pred[0])*dt*math.cos(theta),'y_m':pose.y_m+float(pred[0])*dt*math.sin(theta)}]
            self.adapted_predicted_motion=list(self.predicted_motion)
            if self.frozen_model is not None:
                frozen=self.frozen_model.predict([action.u])[0]
                frozen_theta=pose.theta_rad+float(frozen[1])*dt/2
                self.frozen_predicted_motion=[{'x_m':pose.x_m,'y_m':pose.y_m},
                    {'x_m':pose.x_m+float(frozen[0])*dt*math.cos(frozen_theta),'y_m':pose.y_m+float(frozen[0])*dt*math.sin(frozen_theta)}]
            self._pulse(action,generation); count+=1
            self._apply_pending_mutations(generation)
            if self.change_detection.get('detected'):
                self.frozen_model=copy.deepcopy(self.model)
                self.body_change_signal={
                    'kind':'body_model_mismatch','source':'camera_prediction_residual',
                    'score':self.change_detection.get('score'),'threshold':self.change_detection.get('threshold'),
                    'evidence_count':self.change_detection.get('evidence_count'),
                    'consecutive_count':self.change_detection.get('consecutive_count'),
                    'privileged_mutation_signal':False,'detected_at':self.now,
                }
                mismatch_event={key:value for key,value in self.body_change_signal.items() if key!='kind'}
                self._event('model_mismatch',{'signal_kind':self.body_change_signal['kind'],
                    **mismatch_event,'frozen_model_id':self.frozen_model.model_id})
                self.recovery_phase='body model mismatch detected; selecting informative experiments'
                self.model_ready=False
                self._learn(generation,recovery=True)
                self._change_recovered=True
                self.change_detector.reset()
                self.change_detection=self.change_detector.status().to_dict()
                self.safety.begin_budget_window(self.now)
                self._set_state(generation,'NAVIGATING')

    def _apply_pending_mutations(self,generation):
        with self.lock:
            self.safety.assert_current(generation)
            pending,self._pending_mutations=self._pending_mutations,[]
        if not pending: return
        for name,request_id in pending:
            self.actuator.mutate(name)
            self._drain_audit()

    def _navigate_route(self,generation):
        started=self.now; results=[]
        for index,point in enumerate(tuple(self.route)):
            with self.lock:
                self.safety.assert_current(generation)
                self.route_index=index
                self.target=(point['x_m'],point['y_m'])
            results.append(self._navigate(generation))
        result={'success':True,'waypoints':len(results),'actions':self.safety.actions,
                'elapsed_s':self.now-started,'target':self.target}
        self._event('route_result',result)
        return result

    def _run_job(self,name,generation):
        try:
            if name in {'navigate','adaptation-challenge'}: self._job_result=self._navigate(generation)
            elif name=='navigate-route': self._job_result=self._navigate_route(generation)
            else:
                self._job_result=self._learn(generation,name in {'recover','adaptation-challenge'})
                if name=='recover': self._change_recovered=True
            self.safety.assert_current(generation)
            self.safety.active=False; self.safety.latched=True
            self.actuator.stop(); self.writer.flush()
        except Exception as exc:
            self._job_error=str(exc)
            if generation==self.safety.generation: self._stop(str(exc),fault=True)
            if name in {'navigate','navigate-route','adaptation-challenge'}:
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
            if name=='inject-mutation':
                allowed={'reverse_left','reverse_right','reverse_both','swap','weaken_left','random_mashup'}
                mutation=payload.get('mapping')
                if mutation not in allowed: raise ValueError('unknown mutation')
                if not self.config.live_mutation_enabled: raise ValueError('live mutation is disabled for this configuration')
                if not self.busy or self.state not in {'NAVIGATING','RECOVERING'}: raise ValueError('mutation requires active navigation')
                if payload.get('owner_id')!=self.safety.owner: raise ValueError('active operator owner required')
                change_id=uuid.uuid4().hex[:12]
                self._pending_mutations.append((mutation,change_id))
                return {'ok':True,'change_id':change_id,'queued':True}
            if name=='adaptation-challenge':
                if self.busy: raise ValueError('another episode is active')
                if self.config.mode=='hardware' and not self._hardware_connected: raise ValueError('connect hardware explicitly first')
                if not self.config.live_mutation_enabled: raise ValueError('live mutation is disabled for this configuration')
                if not self.model_ready or self.target is None: raise ValueError('validated model and target required')
                self._observe()
                if math.hypot(self.target[0]-self.pose.x_m,self.target[1]-self.pose.y_m)<=self.config.goal_contact_radius_m:
                    raise ValueError('choose a target outside the robot footprint')
                self._stop('adaptation challenge mutation')
                self.change_detector.reset(); self.change_detection=self.change_detector.status().to_dict()
                self.change_detected=False; self._change_recovered=False; self.body_change_signal=None
                self.actuator.mutate(payload.get('mapping') or 'random_mashup')
                self._drain_audit()
                generation=self.safety.start(payload.get('owner_id'),self.now)
                try: self._check(generation)
                except Exception:
                    self.safety.stop('start safety gate rejected'); raise
                self.busy=True; self.stop_reason=None; self._cancel.clear()
                self._job_error=None; self._monitor_error=None; self._job_result=None
                self._job=threading.Thread(target=self._run_job,args=(name,generation),daemon=True,name='darwin-challenge')
                self._job.start()
                return {'ok':True,'job':name,'generation':generation,'mutation':'hidden'}
            if name in {'start-calibration','recover','navigate','navigate-route'}:
                if self.busy: raise ValueError('another episode is active')
                self._pending_mutations=[]
                if name=='start-calibration':
                    self.target=None; self.route=[]; self.route_index=None
                if self.config.mode=='hardware' and not self._hardware_connected: raise ValueError('connect hardware explicitly first')
                if name=='navigate' and (not self.model_ready or self.target is None): raise ValueError('validated model and target required')
                if name=='navigate-route' and (not self.model_ready or not self.route): raise ValueError('validated model and route required')
                if name=='recover' and self.frozen_model is None: raise ValueError('scramble a trained model first')
                self._observe()
                gen=self.safety.start(payload.get('owner_id'),self.now)
                try: self._check(gen,exploration=name not in {'navigate','navigate-route'},
                    allow_boundary_recovery=name in {'navigate','navigate-route'} and self.model_ready)
                except Exception:
                    self.safety.stop('start safety gate rejected'); raise
                if name in {'navigate','navigate-route'}:
                    self.change_detector.reset(); self.change_detection=self.change_detector.status().to_dict(); self.change_detected=False
                    self._change_recovered=False; self.body_change_signal=None
                    self.boundary_recovery_active=False
                self.busy=True; self.stop_reason=None; self._cancel.clear()
                self._job_error=None; self._monitor_error=None; self._job_result=None
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
                self.target=(x,y); self.route=[]; self.route_index=None
                self._event('target',{'target':self.target}); return {'ok':True,'target':self.target}
            if name=='route':
                if self.busy: raise ValueError('stop before changing route')
                raw=payload.get('points')
                if not isinstance(raw,list) or not 2<=len(raw)<=16: raise ValueError('route requires 2 to 16 waypoints')
                left,right,bottom,top=self.config.safe_bounds; route=[]
                for item in raw:
                    if isinstance(item,dict): values=(item.get('x_m'),item.get('y_m'))
                    elif isinstance(item,(list,tuple)) and len(item)==2: values=item
                    else: raise ValueError('route waypoint must contain x_m and y_m')
                    x,y=map(float,values)
                    if not math.isfinite(x+y) or not left<=x<=right or not bottom<=y<=top:
                        raise ValueError('route waypoint outside safe arena')
                    route.append({'x_m':x,'y_m':y})
                self.route=route; self.route_index=0; self.target=(route[0]['x_m'],route[0]['y_m'])
                self._event('route',{'points':route}); return {'ok':True,'route':route}
            if name in {'scramble','reset-model','reset','calibration','connect','recenter'} and self.busy:
                raise ValueError('stop and wait for active pulse before changing state')
            if name=='scramble':
                if not self.model_ready: raise ValueError('learn a model before scramble')
                self._stop('scramble')
                self.frozen_model=copy.deepcopy(self.model)
                self.actuator.scramble(payload.get('mapping'))
                self._drain_audit()
                self.model_ready=False; self.samples=[]; self.heldout=[]; self.latest_residual=None; self.latest_prediction_comparison=None
                self.change_detector.reset(); self.change_detection=self.change_detector.status().to_dict(); self.change_detected=False; self.body_change_signal=None
                self.recovery_phase='scrambled; recover with fresh observations'
                self._event('scramble',{'model_frozen':self.frozen_model.model_id})
                return {'ok':True}
            if name in {'reset-model','reset'}:
                from darwin.learning.model import MotionModel
                self._stop('model reset'); self.model=MotionModel(ridge_lambda=self.config.ridge_lambda)
                self.model_ready=False; self.frozen_model=None; self.samples=[]; self.heldout=[]; self.metrics={}; self.latest_residual=None; self.latest_prediction_comparison=None; self.body_change_signal=None
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
                self.model_ready=False; self.frozen_model=None; self.samples=[]; self.heldout=[]; self.metrics={}; self.latest_residual=None; self.latest_prediction_comparison=None; self.body_change_signal=None; self._stop('calibration changed; relearn required')
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

    @staticmethod
    def _public_model_field(model, grid_size=9):
        """Render-safe predictions from a learned model, never actuator truth."""
        if model is None or model.coefficients is None or model.model_id is None:
            return None
        levels=np.linspace(-1.,1.,grid_size)
        actions=np.asarray([(left,right) for right in levels for left in levels])
        predictions=model.predict(actions)
        if not np.isfinite(predictions).all():
            return None
        return {
            'model_id':model.model_id,
            'grid_size':grid_size,
            'coefficients':model.coefficients.tolist(),
            'points':[{'left':float(action[0]),'right':float(action[1]),
                       'v_mps':float(prediction[0]),'omega_radps':float(prediction[1])}
                      for action,prediction in zip(actions,predictions)],
        }

    def _public_model_visualization(self):
        observations=[]
        for sample,valid in [(sample,True) for sample in self.samples[-100:]]+[(sample,False) for sample in self.rejected[-20:]]:
            values=(sample.u1,sample.u2,sample.v_mps,sample.omega_radps)
            if not np.isfinite(values).all():
                continue
            observations.append({'left':float(sample.u1),'right':float(sample.u2),
                                 'v_mps':float(sample.v_mps),'omega_radps':float(sample.omega_radps),
                                 'valid':valid})
        return {'current':self._public_model_field(self.model if self.model_ready else None),
                'frozen':self._public_model_field(self.frozen_model),
                'observations':observations}

    def list_runs(self):
        return [{'run_id':p.name,'path':str(p)} for p in sorted(Path(self.writer.path).parent.iterdir(),reverse=True) if p.is_dir() and (p/'metadata.json').exists()][:100]

    def snapshot(self):
        pose=asdict(self.pose) if self.pose else None
        age=max(0,(self.now-self.pose.observed_at)*1000) if self.pose else None
        if self.faults.get('stale_frames'): age=max(age or 0,self.config.max_frame_age_ms+1)
        return {'mode':self.config.mode,'state':self.state,'stop_reason':self.stop_reason,'run_id':self.run_id,
            'pose':pose,'target':self.target,'route':self.route,'route_index':self.route_index,
            'trail':self.trail[-500:],'predicted_motion':self.predicted_motion,
            'transport_health':'healthy' if self._healthy() else 'disconnected','frame_age_ms':age,
            'ack_age_ms':max(0,(self.now-self.last_receipt.ack_at)*1000) if self.last_receipt and self.last_receipt.ack_at is not None else None,
            'valid_sample_count':len(self.samples),'rejected_sample_count':len(self.rejected),'heldout_sample_count':len(self.heldout),
            'model_id':self.model.model_id if self.model_ready else None,'validation_metrics':self.metrics,
            'recovery_phase':self.recovery_phase,'busy':self.busy,'owner_id':self.safety.owner if self.safety.active else None,
            'calibration':self.calibration.to_dict() if self.calibration else None,'events':self.events[-25:],
            'latest_residual':self.latest_residual,'latest_prediction_comparison':self.latest_prediction_comparison,
            'change_detection':{**self.change_detection,'detected':self.change_detected},
            'body_change_signal':self.body_change_signal,
            'model_visualization':self._public_model_visualization(),
            'adaptation_complete':self._change_recovered,
            'model_uncertainty':self.model_uncertainty,
            'frozen_predicted_motion':self.frozen_predicted_motion,
            'adapted_predicted_motion':self.adapted_predicted_motion,
            'model_memory':{'count':len(self.model_memory.entries),'matched_model_id':self.matched_model_id},
            'live_mutation_enabled':self.config.live_mutation_enabled,
            'boundary_recovery_active':self.boundary_recovery_active,
            'obstacles':self.obstacles,'faults':dict(self.faults),'model_ready':self.model_ready,
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
