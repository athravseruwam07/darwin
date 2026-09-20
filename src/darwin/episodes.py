"""Pose-only transition construction. A complete stopped pulse is one trial."""
import math
from darwin.types import Pose, RequestedAction, Transition

def wrap(angle): return math.atan2(math.sin(angle), math.cos(angle))

def transition(action: RequestedAction, start: Pose, end: Pose, config_id: str,
               timing_uncertainty_ms=0., invalid_reason=None, expected_elapsed_s=None):
    dt = end.observed_at-start.observed_at
    vals = [start.x_m,start.y_m,start.theta_rad,end.x_m,end.y_m,end.theta_rad,dt]
    reason = invalid_reason
    if not start.valid or not end.valid: reason = reason or "invalid tracking"
    if not all(math.isfinite(v) for v in vals): reason = reason or "nonfinite pose"
    if dt <= 0: reason = reason or "nonpositive duration"
    if end.frame_id <= start.frame_id: reason = reason or "stale frame identity"
    if start.calibration_id != end.calibration_id: reason = reason or "calibration changed"
    if not all(math.isfinite(u) and -1 <= u <= 1 for u in action.u): reason = reason or "invalid abstract action"
    if not math.isfinite(timing_uncertainty_ms) or timing_uncertainty_ms < 0: reason = reason or "invalid timing uncertainty"
    if expected_elapsed_s is not None and abs(dt-expected_elapsed_s) > max(.03, timing_uncertainty_ms/1000): reason = reason or "inconsistent full-cycle duration"
    if dt > 2.: reason = reason or "observation gap"
    if timing_uncertainty_ms > 150: reason = reason or "uncertain actuation timing"
    dtheta = wrap(end.theta_rad-start.theta_rad)
    if abs(dtheta) > .9: reason = reason or "excessive rotation"
    dx,dy = end.x_m-start.x_m,end.y_m-start.y_m
    mid = start.theta_rad+dtheta/2
    forward = math.cos(mid)*dx+math.sin(mid)*dy
    lateral = -math.sin(mid)*dx+math.cos(mid)*dy
    if abs(lateral) > .04 or math.hypot(dx,dy) > .2: reason = reason or "contact or manual intervention"
    return Transition(action.id,action.episode_id,*action.u,start,end,dt,forward,lateral,dtheta,
                      forward/dt if dt>0 else 0.,dtheta/dt if dt>0 else 0.,reason is None,
                      reason,timing_uncertainty_ms,config_id=config_id)
