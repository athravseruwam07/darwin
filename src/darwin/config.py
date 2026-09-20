"""Validated, immutable configuration; hardware geometry must be measured."""
from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib
import json
import math
import yaml

@dataclass(frozen=True)
class Config:
    mode: str = "simulation"
    host: str = "127.0.0.1"
    port: int = 8770
    seed: int = 42
    observation: str = "vision"
    arena_width_m: float = 1.0
    arena_height_m: float = 1.0
    robot_radius_m: float = .08
    boundary_margin_m: float = .15
    pulse_ms: int = 120
    settle_ms: int = 300
    initial_trials: int = 24
    validation_trials: int = 12
    ridge_lambda: float = .001
    goal_radius_m: float = .06
    goal_dwell_ms: int = 500
    max_episode_actions: int = 100
    max_episode_seconds: float = 45
    max_frame_age_ms: int = 150
    operator_lease_ms: int = 1000
    pwm_scale: int = 60
    max_pwm: int = 90
    fallback_ttl_ms: int = 200
    ack_timeout_ms: int = 100
    serial_port: str | None = None
    baudrate: int = 115200
    camera_backend: str = "simulated"
    camera_index: int = 0
    camera_path: str | None = None
    calibration_path: str | None = None
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    marker_id: int = 7
    heading_offset_rad: float = 0.0
    hardware_confirmed: bool = False
    timestamp_bound_ms: float | None = None
    measured_probe_bound_m: float | None = None
    stationary_position_tolerance_m: float = .002
    stationary_yaw_tolerance_rad: float = .03
    stationary_window_s: float = .15
    candidate_levels: tuple = (-1., -.6, 0., .6, 1.)
    desired_max_speed_mps: float = .08
    desired_max_yaw_radps: float = .7
    plant_variant: str = "linear"
    mismatch_threshold: float = .25
    mismatch_required_exceedances: int = 3
    recovery_trials: int = 12
    recovery_validation_trials: int = 8
    model_memory_match_distance: float = .15
    obstacle_detection_enabled: bool = False
    live_mutation_enabled: bool | None = None
    brain_enabled: bool = True
    brain_model: str = "gpt-4o-mini"
    brain_timeout_s: float = 6.0
    brain_max_thoughts: int = 40
    brain_min_interval_s: float = 2.0
    brain_voice_enabled: bool = True
    brain_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    brain_voice_model: str = "eleven_turbo_v2_5"
    brain_voice_timeout_s: float = 12.0

    def __post_init__(self):
        if self.live_mutation_enabled is None:
            object.__setattr__(self,'live_mutation_enabled',self.mode=='simulation')
        for k, v in asdict(self).items():
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError(f"{k} must be finite")
        for key in ('port','seed','pulse_ms','settle_ms','initial_trials','validation_trials','goal_dwell_ms','max_episode_actions','max_frame_age_ms','operator_lease_ms','pwm_scale','max_pwm','fallback_ttl_ms','ack_timeout_ms','baudrate','camera_width','camera_height','camera_fps','marker_id','mismatch_required_exceedances','recovery_trials','recovery_validation_trials'):
            if type(getattr(self,key)) is not int: raise ValueError(f'{key} must be an integer')
        if type(self.brain_enabled) is not bool or type(self.brain_voice_enabled) is not bool: raise ValueError('narration flags must be boolean')
        if type(self.brain_max_thoughts) is not int or not 4 <= self.brain_max_thoughts <= 400: raise ValueError('invalid narration history size')
        if min(self.brain_timeout_s, self.brain_voice_timeout_s) <= 0 or self.brain_min_interval_s < 0: raise ValueError('invalid narration timing')
        if not all(isinstance(value, str) and value for value in (self.brain_model, self.brain_voice_id, self.brain_voice_model)): raise ValueError('narration model and voice identifiers must be non-empty strings')
        if type(self.hardware_confirmed) is not bool or type(self.obstacle_detection_enabled) is not bool or type(self.live_mutation_enabled) is not bool: raise ValueError('hardware, obstacle, and mutation flags must be boolean')
        if self.measured_probe_bound_m is not None and (not math.isfinite(self.measured_probe_bound_m) or self.measured_probe_bound_m <= 0): raise ValueError('invalid measured probe travel bound')
        if min(self.stationary_position_tolerance_m,self.stationary_yaw_tolerance_rad,self.stationary_window_s)<=0: raise ValueError('invalid stationary observation thresholds')
        if self.camera_backend not in {'simulated','oak','webcam','video'}: raise ValueError('unknown camera backend')
        if min(self.camera_width,self.camera_height)<64 or self.goal_dwell_ms<50: raise ValueError('invalid camera resolution or dwell')
        if self.mode not in {"simulation", "hardware", "replay"}: raise ValueError("unknown mode")
        if self.host not in {"127.0.0.1", "localhost", "::1"}: raise ValueError("localhost only")
        if not 1024 <= self.port <= 65535: raise ValueError("invalid UI port")
        if self.observation not in {"vision", "pose"}: raise ValueError("invalid observation")
        if self.plant_variant not in {"linear", "noisy", "nonlinear"}: raise ValueError("invalid plant variant")
        if not 0 < self.pwm_scale <= self.max_pwm <= 90: raise ValueError("PWM exceeds firmware bounds")
        if not 20 <= self.pulse_ms < self.fallback_ttl_ms <= 250: raise ValueError("invalid pulse/TTL")
        if self.settle_ms < 0 or self.ridge_lambda < 0: raise ValueError("negative settle/ridge")
        if min(self.robot_radius_m, self.boundary_margin_m, self.goal_radius_m) <= 0: raise ValueError("invalid geometry")
        if min(self.arena_width_m, self.arena_height_m) <= 2*(self.robot_radius_m+self.boundary_margin_m)+.1: raise ValueError("arena has no safe interior")
        if min(self.initial_trials,self.validation_trials,self.recovery_trials,self.recovery_validation_trials) < 6: raise ValueError("insufficient independent trials")
        if self.recovery_validation_trials < 8: raise ValueError("recovery validation needs straight and turn coverage")
        if self.mismatch_required_exceedances < 1 or self.mismatch_threshold <= 0 or self.model_memory_match_distance < 0: raise ValueError('invalid adaptation thresholds')
        if min(self.max_episode_actions,self.max_episode_seconds,self.max_frame_age_ms,self.operator_lease_ms,self.ack_timeout_ms,self.camera_fps) <= 0: raise ValueError("invalid limits")
        if not 0 <= self.marker_id < 50: raise ValueError("marker ID outside dictionary")
        if not all(math.isfinite(x) and -1 <= x <= 1 for x in self.candidate_levels) or 0 not in self.candidate_levels: raise ValueError("invalid candidate levels")
        if self.mode == "hardware" and self.camera_backend == "simulated": raise ValueError("hardware cannot use simulated camera")
        if self.timestamp_bound_ms is not None and (not math.isfinite(self.timestamp_bound_ms) or self.timestamp_bound_ms < 0): raise ValueError("invalid timestamp bound")

    @property
    def config_id(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]

    @property
    def safe_bounds(self):
        m = self.robot_radius_m+self.boundary_margin_m
        return (m, self.arena_width_m-m, m, self.arena_height_m-m)

    @property
    def physical_bounds(self):
        """Legal robot-center bounds when its footprint only touches red."""
        m = self.robot_radius_m
        return (m, self.arena_width_m-m, m, self.arena_height_m-m)

    @property
    def goal_contact_radius_m(self):
        """Center-to-target distance where the robot footprint touches the target."""
        return max(self.robot_radius_m,self.goal_radius_m)

    @property
    def boundary_recovery_bounds(self):
        """Physical bounds with one measured pulse of emergency reserve."""
        reserve = self.measured_probe_bound_m or .04
        m = self.robot_radius_m+reserve
        return (m, self.arena_width_m-m, m, self.arena_height_m-m)

    def public(self): return {**asdict(self),'goal_contact_radius_m':self.goal_contact_radius_m}

def load_config(path=None, **overrides):
    data = yaml.safe_load(Path(path).read_text()) if path else {}
    data = data or {}
    if not isinstance(data, dict): raise ValueError("configuration must be a mapping")
    data.update({k:v for k,v in overrides.items() if v is not None})
    if "candidate_levels" in data: data["candidate_levels"] = tuple(data["candidate_levels"])
    return Config(**data)
