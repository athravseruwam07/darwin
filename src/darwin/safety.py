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
        self.budget_actions=0
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
            self.owner=owner; self.last_lease=time.monotonic(); self.started_at=now; self.actions=0; self.budget_actions=0
            return self.generation

    def begin_budget_window(self, now):
        """Start a fresh bounded phase without erasing episode totals."""
        with self.lock:
            if not self.active or self.latched:
                raise SafetyViolation(self.reason or "cancelled episode")
            self.started_at=now
            self.budget_actions=0

    def stop(self, reason="operator stop"):
        with self.lock:
            self.generation+=1; self.active=False; self.latched=True; self.reason=reason

    def assert_current(self, generation):
        if generation!=self.generation or not self.active or self.latched:
            raise SafetyViolation(self.reason or "cancelled episode")

    def check(self, pose, now, generation, *, transport_healthy=True, exploration=False,
              allow_boundary_recovery=False):
        with self.lock:
            self.assert_current(generation)
            if time.monotonic()-self.last_lease > self.config.operator_lease_ms/1000:
                raise SafetyViolation("operator lease expired")
            if now-self.started_at >= self.config.max_episode_seconds: raise SafetyViolation("episode time budget")
            if self.budget_actions >= self.config.max_episode_actions: raise SafetyViolation("episode action budget")
            if not transport_healthy: raise SafetyViolation("transport disconnected or unhealthy")
            if pose is None or not pose.valid: raise SafetyViolation("tracking invalid")
            if not all(math.isfinite(v) for v in (pose.x_m,pose.y_m,pose.theta_rad,pose.observed_at)):
                raise SafetyViolation("nonfinite tracking")
            timestamp_bound=(self.config.timestamp_bound_ms or 0.)/1000 if self.config.mode=='hardware' else 0.
            if now-pose.observed_at+timestamp_bound > self.config.max_frame_age_ms/1000 or now < pose.observed_at-.001:
                raise SafetyViolation("stale frame")
            physical=self.config.physical_bounds
            if not physical[0] < pose.x_m < physical[1] or not physical[2] < pose.y_m < physical[3]:
                raise SafetyViolation("physical red boundary / footprint crossed")
            operating=self.config.safe_bounds
            inside_operating=(operating[0]<=pose.x_m<=operating[1] and operating[2]<=pose.y_m<=operating[3])
            if exploration:
                guard=self.config.measured_probe_bound_m or .04
                if not operating[0]+guard<=pose.x_m<=operating[1]-guard or not operating[2]+guard<=pose.y_m<=operating[3]-guard:
                    raise SafetyViolation("outside green recovery boundary during exploration")
            elif not inside_operating:
                if not allow_boundary_recovery:
                    raise SafetyViolation("outside green recovery boundary")
                recovery=self.config.boundary_recovery_bounds
                if not recovery[0]<=pose.x_m<=recovery[1] or not recovery[2]<=pose.y_m<=recovery[3]:
                    raise SafetyViolation("insufficient red boundary reserve for inward recovery")
            if self.config.mode=="hardware":
                if self.config.camera_backend=='video': raise SafetyViolation('recorded video cannot authorize physical motion')
                if self.config.measured_probe_bound_m is None: raise SafetyViolation('measured maximum probe travel required')
                if not self.config.hardware_confirmed: raise SafetyViolation("raised-wheel readiness not confirmed")
                if not self.config.calibration_path: raise SafetyViolation("measured hardware calibration required")
                if self.config.timestamp_bound_ms is None: raise SafetyViolation("camera timestamp bound unverified")
                if self.config.timestamp_bound_ms>=self.config.max_frame_age_ms: raise SafetyViolation("camera timestamp bound too large")
            return True
