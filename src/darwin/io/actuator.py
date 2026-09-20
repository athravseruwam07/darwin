"""Privileged hidden motor mapping and cancellable, stop-start pulse lifecycle."""
import math, threading, time, uuid
import numpy as np
from darwin.types import ActuationReceipt

class HardwareActuator:
    def __init__(self,transport,config,safety_check=None):
        self.transport=transport; self.config=config; self.safety_check=safety_check
        self._map=np.eye(2); self._generation=0; self._sequence=0; self._lock=threading.RLock()
        self._executing=threading.Lock(); self.audit_records=[]
    def _check(self,generation):
        if generation!=self._generation: raise RuntimeError('cancelled by STOP')
        if self.safety_check:
            reason=self.safety_check()
            if reason: raise RuntimeError(str(reason))
        if hasattr(self.transport,'poll_health'): self.transport.poll_health()
        if not self.transport.health.get('connected'): raise RuntimeError('transport disconnected')
        if self.transport.health.get('error'): raise RuntimeError('transport fault: '+str(self.transport.health['error']))
    def execute(self,action):
        sent=time.monotonic(); ack=None; generation=self._generation
        if not self._executing.acquire(blocking=False): return ActuationReceipt(action.id,0,sent,None,False,'action already executing')
        try:
            if len(action.u)!=2 or not all(math.isfinite(v) and -1<=v<=1 for v in action.u) or not 20<=action.pulse_ms<self.config.fallback_ttl_ms: raise ValueError('invalid action')
            with self._lock:
                self._check(generation)
                self.transport.arm()
                self._check(generation)
                physical=np.rint(np.clip(self._map@np.asarray(action.u),-1,1)*self.config.pwm_scale).astype(int)
                self._sequence+=1; sent=time.monotonic()
                ack=self.transport.send_motor(self._sequence,int(physical[0]),int(physical[1]),self.config.fallback_ttl_ms)
                self.audit_records.append({'action_id':action.id,'sequence':self._sequence,'sent_at':sent,'ack_at':ack,'physical_pwm':physical.tolist()})
            deadline=sent+action.pulse_ms/1000
            while time.monotonic()<deadline:
                self._check(generation); time.sleep(min(.005,max(0,deadline-time.monotonic())))
            # Normal STOP must not invalidate the authorized enclosing episode.
            self.transport.stop()
            if not self.transport.health.get('connected') or self.transport.health.get('error'): raise RuntimeError('STOP failed or firmware fault: '+str(self.transport.health.get('error')))
            deadline=time.monotonic()+self.config.settle_ms/1000
            while time.monotonic()<deadline:
                self._check(generation); time.sleep(min(.005,max(0,deadline-time.monotonic())))
            self._check(generation)
            return ActuationReceipt(action.id,self._sequence,sent,ack,True)
        except Exception as exc:
            self.stop(); return ActuationReceipt(action.id,self._sequence,sent,ack,False,str(exc))
        finally: self._executing.release()
    def stop(self):
        self._generation+=1
        # SerialTransport stop also invalidates its pending exchange immediately.
        with self._lock:
            self.transport.stop()
    def scramble(self,name=None):
        self.stop()
        if self._executing.locked(): raise RuntimeError('wait for cancelled action before scramble')
        maps={'identity':np.eye(2),'swap':np.array([[0,1],[1,0]]),'reverse_one':np.diag([-1,1]),'reverse_both':-np.eye(2),'unequal':np.diag([.7,1.])}
        if name is None: name='reverse_one'
        if name not in maps: raise ValueError('unknown scramble')
        self._map=maps[name]; identity=uuid.uuid4().hex[:12]
        self.audit_records.append({'event':'scramble','change_id':identity,'at':time.monotonic(),'mapping':self._map.tolist()})
        return identity
