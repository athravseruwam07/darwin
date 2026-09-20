"""Structured, public narration facts.

Only camera-measured observations and learned model state are copied here. The
simulator plant, the actuator mutation map, and any privileged inverse are never
read, so nothing sent to a language model can reveal the hidden answer.
"""
from __future__ import annotations
import math

PUBLIC_KEYS = ('mode','state','busy','recovery_phase','stop_reason','model_id','model_ready',
               'valid_sample_count','rejected_sample_count','heldout_sample_count','pose','target',
               'change_detection','model_uncertainty','latest_residual','validation_metrics',
               'frame_age_ms','ack_age_ms','transport_health','boundary_recovery_active',
               'adaptation_complete','body_change_signal','model_memory','events')

def number(value, digits=None):
    """Return a finite float, or None for anything unusable."""
    if isinstance(value,bool) or not isinstance(value,(int,float)): return None
    value=float(value)
    if not math.isfinite(value): return None
    return round(value,digits) if digits is not None else value

def count(value):
    """Return a whole-number count, or None when the field is unusable."""
    value=number(value)
    return None if value is None else int(round(value))

def _text(value, limit=160):
    if not isinstance(value,str): return None
    value=' '.join(value.split())
    return value[:limit] or None

def _pose(raw):
    if not isinstance(raw,dict): return None
    x,y,theta=number(raw.get('x_m'),4),number(raw.get('y_m'),4),number(raw.get('theta_rad'),4)
    if x is None or y is None or theta is None: return None
    return {'x_m':x,'y_m':y,'theta_rad':theta,'valid':bool(raw.get('valid')),'quality':number(raw.get('quality'),3)}

def _point(raw):
    if isinstance(raw,dict): raw=(raw.get('x_m'),raw.get('y_m'))
    if not isinstance(raw,(list,tuple)) or len(raw)!=2: return None
    x,y=number(raw[0],4),number(raw[1],4)
    return None if x is None or y is None else [x,y]

def _metrics(raw, key):
    entry=raw.get(key) if isinstance(raw,dict) else None
    if not isinstance(entry,dict): return None
    normalized=number(entry.get('normalized_rmse'),5)
    if normalized is None: return None
    return {'normalized_rmse':normalized,'v_rmse_mps':number(entry.get('v_rmse_mps'),5),
            'omega_rmse_radps':number(entry.get('omega_rmse_radps'),4)}

def cognition_facts(snapshot, config=None):
    """Project a runtime snapshot onto the narration-safe fact packet."""
    snapshot=snapshot if isinstance(snapshot,dict) else {}
    config=config if isinstance(config,dict) else {}
    change=snapshot.get('change_detection') if isinstance(snapshot.get('change_detection'),dict) else {}
    score,threshold=number(change.get('score'),4),number(change.get('threshold'),4)
    metrics=snapshot.get('validation_metrics') if isinstance(snapshot.get('validation_metrics'),dict) else {}
    frozen,adapted=_metrics(metrics,'frozen'),_metrics(metrics,'adapted')
    improvement=None
    if frozen and adapted and frozen['normalized_rmse']>0:
        improvement=number(100*(1-adapted['normalized_rmse']/frozen['normalized_rmse']),1)
    pose,target=_pose(snapshot.get('pose')),_point(snapshot.get('target'))
    residual=snapshot.get('latest_residual') if isinstance(snapshot.get('latest_residual'),dict) else {}
    memory=snapshot.get('model_memory') if isinstance(snapshot.get('model_memory'),dict) else {}
    signal=snapshot.get('body_change_signal') if isinstance(snapshot.get('body_change_signal'),dict) else None
    return {
        'mode':_text(snapshot.get('mode'),24) or 'unknown',
        'state':_text(snapshot.get('state'),24) or 'UNKNOWN',
        'busy':bool(snapshot.get('busy')),
        'phase':_text(snapshot.get('recovery_phase')),
        'stop_reason':_text(snapshot.get('stop_reason')),
        'model_id':_text(snapshot.get('model_id'),32),
        'model_ready':bool(snapshot.get('model_ready')),
        'model_generation':count(memory.get('count')),
        'samples':{'valid':count(snapshot.get('valid_sample_count')),
                   'rejected':count(snapshot.get('rejected_sample_count')),
                   'heldout':count(snapshot.get('heldout_sample_count'))},
        'change':{'score':score,'threshold':threshold,
                  'ratio':number(score/threshold,3) if score is not None and threshold else None,
                  'evidence_count':count(change.get('evidence_count')),
                  'consecutive_count':count(change.get('consecutive_count')),
                  'detected':bool(change.get('detected'))},
        'sensed_change':None if signal is None else {
            'source':_text(signal.get('source'),48) or 'camera_prediction_residual',
            'score':number(signal.get('score'),4),'threshold':number(signal.get('threshold'),4),
            'evidence_count':count(signal.get('evidence_count')),
            'privileged_mutation_signal':bool(signal.get('privileged_mutation_signal'))},
        'uncertainty':number(snapshot.get('model_uncertainty'),5),
        'residual':{'v_mps':number(residual.get('v_mps'),5),'omega_radps':number(residual.get('omega_radps'),4)},
        'metrics':{'frozen':frozen,'adapted':adapted,'current':_metrics(metrics,'current') or _metrics(metrics,'before'),
                   'improvement_pct':improvement},
        'pose':pose,'target':target,
        'distance_to_target_m':None if not (pose and target) else number(math.hypot(target[0]-pose['x_m'],target[1]-pose['y_m'])),
        'goal_contact_radius_m':number(config.get('goal_contact_radius_m'),4),
        'tracking_valid':bool(pose and pose['valid']),
        'frame_age_ms':count(snapshot.get('frame_age_ms')),
        'ack_age_ms':count(snapshot.get('ack_age_ms')),
        'transport_health':_text(snapshot.get('transport_health'),32),
        'boundary_recovery':bool(snapshot.get('boundary_recovery_active')),
        'adaptation_complete':bool(snapshot.get('adaptation_complete')),
    }
