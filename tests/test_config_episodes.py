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

def test_goal_contact_radius_uses_the_whole_robot_footprint():
    config=Config(robot_radius_m=.08,goal_radius_m=.06)

    assert config.goal_contact_radius_m==.08
    assert config.public()['goal_contact_radius_m']==.08

def test_cognition_settings_do_not_change_motion_model_identity():
    baseline=Config()
    changed=Config(
        brain_enabled=False,
        brain_model='another-model',
        brain_timeout_s=9,
        brain_voice_enabled=False,
        brain_voice_id='another-voice',
    )

    assert changed.config_id==baseline.config_id

def test_default_voice_is_available_to_free_elevenlabs_api_accounts():
    assert Config().brain_voice_id=='SAz9YHcvj6GT2YYXdXww'

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


def test_navigation_buffer_recovers_but_physical_boundary_still_stops():
    config=Config(boundary_margin_m=.10,robot_radius_m=.08)
    safety=SafetySupervisor(config); generation=safety.start('test',1.)
    # Center is outside the green 18 cm line, but the 8 cm footprint remains
    # inside the red arena boundary.
    assert safety.check(Pose(1,1.,.14,.5,0),1.,generation,allow_boundary_recovery=True)
    with pytest.raises(SafetyViolation,match='green recovery boundary'):
        safety.check(Pose(2,1.01,.14,.5,0),1.01,generation,exploration=True)
    with pytest.raises(SafetyViolation,match='insufficient red boundary reserve'):
        safety.check(Pose(3,1.02,.10,.5,0),1.02,generation,allow_boundary_recovery=True)
    with pytest.raises(SafetyViolation,match='physical red boundary'):
        safety.check(Pose(4,1.03,.079,.5,0),1.03,generation,allow_boundary_recovery=True)


def test_new_bounded_phase_gets_fresh_time_and_action_budget():
    config=Config(max_episode_seconds=.1,max_episode_actions=2)
    safety=SafetySupervisor(config); generation=safety.start('test',1.)
    safety.actions=2
    safety.budget_actions=2
    with pytest.raises(SafetyViolation,match='time budget'):
        safety.check(Pose(1,1.11,.5,.5,0),1.11,generation)

    safety.begin_budget_window(1.11)

    assert safety.actions==2
    assert safety.budget_actions==0
    assert safety.check(Pose(2,1.11,.5,.5,0),1.11,generation)
