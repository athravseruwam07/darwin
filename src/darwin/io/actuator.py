"""Privileged hidden motor mapping and cancellable, stop-start pulse lifecycle."""
import math, threading, time, uuid
import numpy as np
from darwin.types import ActuationReceipt

class HardwareActuator:
    def __init__(self,transport,config,safety_check=None):
        self.transport=transport; self.config=config; self.safety_check=safety_check
        self._map=np.eye(2); self._generation=0; self._sequence=0; self._lock=threading.RLock()
        self._executing=threading.Lock(); self.audit_records=[]
        self._rng=np.random.default_rng(config.seed+104729)
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
        maps={'identity':np.eye(2),'swap':np.array([[0,1],[1,0]]),
              'reverse_left':np.diag([-1,1]),'reverse_right':np.diag([1,-1]),
              'reverse_both':-np.eye(2),'unequal':np.diag([.7,1.])}
        aliases={'reverse_one':'reverse_left','reverse-one':'reverse_left','reverse-left':'reverse_left',
                 'reverse-right':'reverse_right','reverse-both':'reverse_both',
                 'unequal_gains':'unequal','unequal-gains':'unequal','weaken_left':'unequal'}
        if name is None: name='reverse_left'
        name=aliases.get(name,name)
        if name not in maps: raise ValueError('unknown scramble')
        self._map=maps[name]; identity=uuid.uuid4().hex[:12]
        self.audit_records.append({'event':'scramble','change_id':identity,'at':time.monotonic(),'mapping':self._map.tolist()})
        return identity
    def mutate(self,name):
        self.stop()
        if self._executing.locked(): raise RuntimeError('mutation must be applied between pulses')
        maps={'reverse_left':np.diag([-1,1]),'reverse_right':np.diag([1,-1]),
              'reverse_both':-np.eye(2),'swap':np.array([[0,1],[1,0]]),'weaken_left':np.diag([.7,1.])}
        if name=='random_mashup':
            keys=tuple(maps); matrix=None; recipe=[]
            for _ in range(32):
                count=int(self._rng.integers(2,len(keys)+1)); chosen=self._rng.choice(keys,size=count,replace=False)
                candidate=np.eye(2)
                for key in chosen: candidate=maps[str(key)]@candidate
                if (np.isfinite(candidate).all() and np.linalg.matrix_rank(candidate)==2 and
                        np.max(np.abs(candidate))<=1 and np.linalg.norm(candidate-np.eye(2))>.1):
                    matrix=candidate; recipe=[str(key) for key in chosen]; break
            if matrix is None: raise RuntimeError('could not generate safe nonidentity mutation')
        elif name in maps: matrix=maps[name]; recipe=[name]
        else: raise ValueError('unknown mutation')
        self._map=matrix; identity=uuid.uuid4().hex[:12]
        self.audit_records.append({'event':'mutation','change_id':identity,'at':time.monotonic(),
                                   'mapping':self._map.tolist(),'recipe':recipe})
        return identity
