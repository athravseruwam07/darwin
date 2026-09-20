"""Shared public contracts. SI units, x right/y up/CCW. Host monotonic seconds.

Synthetic time is one advancing monotonic domain and explicitly labelled synthetic.
No physical channels, mapping matrices, or plant truth belong in these records.
"""
from dataclasses import dataclass, asdict
from typing import Protocol, Any
import numpy as np

FEATURE_VERSION = "linear_with_bias_v1"
MEASUREMENT_VERSION = "pulse_plus_settle_v1"

@dataclass(frozen=True)
class Frame:
    id: int
    image_bgr: np.ndarray
    captured_at: float | None
    received_at: float
    source: str = "simulation"
    timestamp_quality: str = "synthetic"

@dataclass(frozen=True)
class Pose:
    frame_id: int
    observed_at: float
    x_m: float
    y_m: float
    theta_rad: float
    valid: bool = True
    quality: float = 1.0
    calibration_id: str = "simulation"
    invalid_reason: str | None = None

@dataclass(frozen=True)
class RequestedAction:
    id: str
    u: tuple[float, float]
    pulse_ms: int
    policy_id: str = "probe"
    episode_id: str = ""

@dataclass(frozen=True)
class ActuationReceipt:
    action_id: str
    sequence: int
    sent_at: float
    ack_at: float | None
    accepted: bool
    error: str | None = None

@dataclass(frozen=True)
class Transition:
    action_id: str
    episode_id: str
    u1: float
    u2: float
    start_pose: Pose
    end_pose: Pose
    elapsed_s: float
    forward_m: float
    lateral_m: float
    delta_theta_rad: float
    v_mps: float
    omega_radps: float
    valid: bool = True
    rejection_reason: str | None = None
    timing_uncertainty_ms: float = 0.0
    feature_version: str = FEATURE_VERSION
    config_id: str = "simulation"
    measurement_version: str = MEASUREMENT_VERSION

@dataclass(frozen=True)
class ModelPrediction:
    v_mps: float
    omega_radps: float
    model_id: str
    eligible: bool = True

class CameraSource(Protocol):
    def start(self) -> None: ...
    def latest_frame(self) -> Frame | None: ...
    def close(self) -> None: ...

class RobotTransport(Protocol):
    def connect(self) -> None: ...
    def handshake(self) -> str: ...
    def arm(self) -> None: ...
    def send_motor(self, seq: int, a: int, b: int, ttl_ms: int) -> Any: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...

def record(value):
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value

from typing import TypedDict

class RuntimeSnapshot(TypedDict, total=False):
    mode: str
    state: str
    stop_reason: str | None
    run_id: str
    pose: dict | None
    target: tuple[float,float] | None
    trail: list[dict]
    predicted_motion: list[dict]
    transport_health: str
    frame_age_ms: float | None
    ack_age_ms: float | None
    valid_sample_count: int
    rejected_sample_count: int
    model_id: str | None
    validation_metrics: dict
    recovery_phase: str
    busy: bool
    owner_id: str | None
