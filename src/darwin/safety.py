"""Output authorization independent of learner success and UI rendering."""
import math
import threading
import time

class SafetyViolation(RuntimeError): pass

class SafetySupervisor:
    def __init__(self, config):
        self.config=config
        self.generation=0
        self.active=False
        self.latched=True
        self.reason="awaiting operator start"
        self.owner=None
        self.last_lease=0.
        self.started_at=0.
        self.actions=0
        self.lock=threading.RLock()

    def heartbeat(self, owner):
        with self.lock:
            if owner and owner==self.owner:
                self.last_lease=time.monotonic()
                return True
            return False

    def start(self, owner, now):
        with self.lock:
            if self.active: raise SafetyViolation("episode already active")
            if not owner: raise SafetyViolation("operator owner required")
            self.generation+=1
            self.active=True; self.latched=False; self.reason=None
            self.owner=owner; self.last_lease=time.monotonic(); self.started_at=now; self.actions=0
            return self.generation

    def stop(self, reason="operator stop"):
        with self.lock:
            self.generation+=1; self.active=False; self.latched=True; self.reason=reason

    def assert_current(self, generation):
        if generation!=self.generation or not self.active or self.latched:
            raise SafetyViolation(self.reason or "cancelled episode")

    def check(self, pose, now, generation, *, transport_healthy=True, exploration=False):
        with self.lock:
            self.assert_current(generation)
            if time.monotonic()-self.last_lease > self.config.operator_lease_ms/1000:
                raise SafetyViolation("operator lease expired")
            if now-self.started_at >= self.config.max_episode_seconds: raise SafetyViolation("episode time budget")
            if self.actions >= self.config.max_episode_actions: raise SafetyViolation("episode action budget")
            if not transport_healthy: raise SafetyViolation("transport disconnected or unhealthy")
            if pose is None or not pose.valid: raise SafetyViolation("tracking invalid")
            if not all(math.isfinite(v) for v in (pose.x_m,pose.y_m,pose.theta_rad,pose.observed_at)):
                raise SafetyViolation("nonfinite tracking")
            timestamp_bound=(self.config.timestamp_bound_ms or 0.)/1000 if self.config.mode=='hardware' else 0.
            if now-pose.observed_at+timestamp_bound > self.config.max_frame_age_ms/1000 or now < pose.observed_at-.001:
                raise SafetyViolation("stale frame")
            left,right,bottom,top=self.config.safe_bounds
            # Unknown-map probes need a conservative extra travel allowance.
            guard=(self.config.measured_probe_bound_m or .04) if exploration else 0.
            if not left+guard <= pose.x_m <= right-guard or not bottom+guard <= pose.y_m <= top-guard:
                raise SafetyViolation("boundary / footprint margin")
            if self.config.mode=="hardware":
                if self.config.camera_backend=='video': raise SafetyViolation('recorded video cannot authorize physical motion')
                if self.config.measured_probe_bound_m is None: raise SafetyViolation('measured maximum probe travel required')
                if not self.config.hardware_confirmed: raise SafetyViolation("raised-wheel readiness not confirmed")
                if not self.config.calibration_path: raise SafetyViolation("measured hardware calibration required")
                if self.config.timestamp_bound_ms is None: raise SafetyViolation("camera timestamp bound unverified")
                if self.config.timestamp_bound_ms>=self.config.max_frame_age_ms: raise SafetyViolation("camera timestamp bound too large")
            return True
