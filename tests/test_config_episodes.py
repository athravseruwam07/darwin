from dataclasses import replace
import math
import pytest
from darwin.config import Config,load_config
from darwin.episodes import transition
from darwin.types import Pose,RequestedAction
from darwin.safety import SafetySupervisor,SafetyViolation

@pytest.mark.parametrize('kwargs',[{'mode':'magic'},{'host':'0.0.0.0'},{'pwm_scale':91},{'max_pwm':100},{'pulse_ms':250},{'settle_ms':-1},{'arena_width_m':.4},{'ridge_lambda':float('nan')},{'candidate_levels':(0,float('inf'))},{'max_frame_age_ms':0},{'camera_width':12},{'hardware_confirmed':'true'},{'pulse_ms':True},{'measured_probe_bound_m':-.1},{'goal_dwell_ms':0}])
def test_invalid_configs_fail(kwargs):
    with pytest.raises(ValueError): Config(**kwargs)

def test_unknown_config_key_rejected(tmp_path):
    p=tmp_path/'config.yaml';p.write_text('mode: simulation\nhidden_mapping: [[1,0],[0,1]]')
    with pytest.raises(TypeError):load_config(p)

def test_full_cycle_timing_and_boundaries():
    a=RequestedAction('a',(1.,0.),120)
    p=Pose(1,1,.5,.5,math.pi-.02)
    q=Pose(2,1.42,.49,.5,-math.pi+.02)
    t=transition(a,p,q,'c',expected_elapsed_s=.42)
    assert t.valid and abs(t.delta_theta_rad-.04)<1e-10 and t.forward_m>0
    for end,uncertainty,reason in [(replace(q,observed_at=1.02),0,'duration'),(replace(q,calibration_id='changed'),0,'calibration'),(q,float('nan'),'timing'),(replace(q,frame_id=1),0,'stale')]:
        bad=transition(a,p,end,'c',uncertainty,expected_elapsed_s=.42)
        assert not bad.valid and reason in bad.rejection_reason
    assert not transition(a,p,q,'c',invalid_reason='manual pickup').valid

def test_hardware_receive_bound_counts_against_freshness():
    c=Config(mode='hardware',camera_backend='webcam',hardware_confirmed=True,calibration_path='measured.json',timestamp_bound_ms=100,measured_probe_bound_m=.04)
    safety=SafetySupervisor(c);gen=safety.start('test',1)
    with pytest.raises(SafetyViolation,match='stale'):
        safety.check(Pose(1,1,.5,.5,0),1.08,gen)

def test_hardware_measured_geometry_and_video_gates():
    c=Config(mode='hardware',camera_backend='video',hardware_confirmed=True,calibration_path='measured.json',timestamp_bound_ms=10,measured_probe_bound_m=.04)
    s=SafetySupervisor(c);g=s.start('test',1)
    with pytest.raises(SafetyViolation,match='recorded video'): s.check(Pose(1,1,.5,.5,0),1,g)
    c=replace(c,camera_backend='webcam',measured_probe_bound_m=None)
    s=SafetySupervisor(c);g=s.start('test',1)
    with pytest.raises(SafetyViolation,match='measured maximum'):s.check(Pose(1,1,.5,.5,0),1,g)
