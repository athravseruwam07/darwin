"""Fake-clock actuator and pose sensor, with private map/plant state."""
import math
import uuid
import numpy as np
from darwin.types import Pose, ActuationReceipt
from .plant import DifferentialDrivePlant, hidden_mapping

class SimulationEnvironment:
    def __init__(self, config):
        self.config = config
        self._plant = DifferentialDrivePlant(config.seed,config.plant_variant)
        self._map_name,self._mapping = hidden_mapping('identity')
        self._clock = 1.
        self._seq = 0; self._frame = 0; self._change = 0
        self._rng = np.random.default_rng(config.seed+104729)
        self._faults = set(); self._history = [(self._clock,self._plant.pose.copy())]
        self._last_observation = None
        self.audit_records = []
        self.last_frame = None
        self.observation_delay_s = 0.
        self.dropout_probability = 0.
        self.command_latency_s = .012 if config.plant_variant == 'nonlinear' else 0.

    @property
    def now(self): return self._clock

    @property
    def health(self): return {'connected':'disconnect_serial' not in self._faults,'mode':'simulation','ack_age_ms':0.}

    def truth_for_renderer(self): return tuple(float(v) for v in self._plant.pose)

    def _advance(self, seconds, physical=(0.,0.)):
        steps = max(1,math.ceil(seconds/.01)); dt = seconds/steps
        for _ in range(steps):
            self._plant.step(physical,dt)
            self._clock += dt
            self._history.append((self._clock,self._plant.pose.copy()))
        self._history = self._history[-1000:]

    def advance(self, seconds):
        if seconds < 0 or not math.isfinite(seconds): raise ValueError('invalid clock advance')
        self._advance(seconds)

    def observe(self):
        if 'stale_frames' in self._faults and self._last_observation is not None: return self._last_observation
        self._frame += 1
        desired_time = self._clock-self.observation_delay_s
        timestamp,truth = next(((t,p) for t,p in reversed(self._history) if t <= desired_time+1e-10),self._history[0])
        sigma = .00045 if self.config.plant_variant in {'noisy','nonlinear'} else 0.
        values = truth + self._rng.normal(0,[sigma,sigma,sigma*5])
        values[2] = math.atan2(math.sin(values[2]),math.cos(values[2]))
        invalid = 'hide_marker' in self._faults or self._rng.random() < self.dropout_probability
        self._last_observation = Pose(self._frame,timestamp,*map(float,values),valid=not invalid,quality=0. if invalid else 1.,invalid_reason='synthetic marker dropout' if invalid else None)
        return self._last_observation

    def execute(self, action):
        self._seq += 1; sent = self._clock
        u = np.asarray(action.u,dtype=float)
        if u.shape != (2,) or not np.isfinite(u).all() or np.any(np.abs(u)>1) or not 20 <= action.pulse_ms < self.config.fallback_ttl_ms:
            return ActuationReceipt(action.id,self._seq,sent,None,False,'invalid action')
        if 'disconnect_serial' in self._faults or 'invalid_ack' in self._faults:
            self.stop()
            return ActuationReceipt(action.id,self._seq,sent,None,False,'simulated transport fault')
        physical = np.clip(self._mapping@u,-1,1)
        latency = min(self.command_latency_s,action.pulse_ms/1000)
        self._advance(latency)
        ack = self._clock
        self._advance(action.pulse_ms/1000-latency,physical)
        self._advance(self.config.settle_ms/1000)
        self.audit_records.append({'action_id':action.id,'sequence':self._seq,'sent_at':sent,'ack_at':ack,'map_name':self._map_name,'physical_outputs':physical.tolist(),'map_change_id':self._change,'mode':'simulation'})
        return ActuationReceipt(action.id,self._seq,sent,ack,True)

    def stop(self):
        # STOP removes propulsion; nonlinear residual coast is retained by physics
        # until advance/next execute (and bounded by the configured settle period).
        self.audit_records.append({'kind':'stop','at':self._clock,'mode':'simulation'})

    def scramble(self, name=None):
        self.stop()
        names = ['swap','reverse_one','reverse_both','unequal_gains','identity']
        if name is None: name = names[self._change%len(names)]
        self._map_name,self._mapping = hidden_mapping(name)
        self._change += 1
        change_id = uuid.uuid4().hex
        self.audit_records.append({'kind':'scramble','at':self.now,'map_name':self._map_name,'change_id':change_id,'mode':'simulation'})
        return change_id

    def reset_pose(self, x=.5,y=.5,theta=0):
        if not np.isfinite([x,y,theta]).all(): raise ValueError('nonfinite pose')
        self.stop(); self._plant.pose = np.array([x,y,theta],dtype=float); self._plant.wheel_speed[:] = 0
        self._clock += .001
        self._history = [(self._clock,self._plant.pose.copy())]
        self._last_observation = None
        self.audit_records.append({'kind':'reset_pose','at':self.now,'pose':[x,y,theta],'mode':'simulation','intervention':True})

    def fault(self, name, enabled):
        aliases = {'marker':'hide_marker','stale':'stale_frames','disconnect':'disconnect_serial','boundary':'boundary_approach'}
        name = aliases.get(name,name)
        if name not in {'hide_marker','stale_frames','disconnect_serial','invalid_ack','boundary_approach','delayed_observation','frame_loss'}: raise ValueError('unknown simulation fault')
        if enabled: self._faults.add(name)
        else: self._faults.discard(name)
        if name == 'boundary_approach' and enabled: self.reset_pose(self.config.robot_radius_m+.01,.5,math.pi)
        if name == 'delayed_observation': self.observation_delay_s = .25 if enabled else 0.
        if name == 'frame_loss': self.dropout_probability = .4 if enabled else 0.

    def close(self): self.stop()
