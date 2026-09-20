"""Actual runtime fault, lease and cancellation integration (no hardware)."""
import time
import pytest
from darwin.config import Config
from darwin.runtime import Runtime
from darwin.safety import SafetyViolation


def make(tmp_path,**config):
    return Runtime(Config(observation='pose',**config),realtime=True,run_root=tmp_path/'runs')


def start(r,name='start-calibration'):
    r.command(name,{'owner_id':'operator-test'})


def finish_without_heartbeat(r):
    r._job.join(4)
    assert not r.busy, 'episode failed to terminate promptly'


def motion_count(r):
    return sum('action_id' in row for row in r.env.audit_records)

@pytest.mark.parametrize('fault',['invalid_ack','disconnect_serial','stale_frames','hide_marker','queue_backlog'])
def test_live_fault_latches_and_clearing_fault_does_not_resume(tmp_path,fault):
    r=make(tmp_path)
    try:
        start(r)
        # Inject the underlying condition rather than command('fault'), which
        # itself calls STOP. The runtime must discover and latch it.
        if fault in {'invalid_ack','disconnect_serial'}:
            r.env.fault(fault,True)
        else:
            r.faults[fault]=True
        finish_without_heartbeat(r)
        assert r.state=='FAULT'
        assert r.safety.latched and not r.safety.active
        count=motion_count(r)
        if fault in {'invalid_ack','disconnect_serial'}: r.env.fault(fault,False)
        else: r.faults[fault]=False
        r._observe()
        time.sleep(.06)
        assert r.state=='FAULT' and motion_count(r)==count
        assert not r.safety.active
    finally: r.close()


def test_operator_lease_expiry_during_learning(tmp_path):
    r=make(tmp_path,operator_lease_ms=50)
    try:
        start(r); finish_without_heartbeat(r)
        assert r.state=='FAULT'
        assert 'lease expired' in r.stop_reason
        assert r.safety.latched and not r.safety.active
        count=motion_count(r)
        assert r.command('heartbeat',{'owner_id':'different-viewer'})['ok'] is False
        time.sleep(.06)
        assert motion_count(r)==count
    finally: r.close()


def test_simultaneous_episode_start_rejected(tmp_path):
    r=make(tmp_path)
    try:
        start(r)
        generation=r.safety.generation
        with pytest.raises(ValueError,match='active'): start(r)
        assert r.safety.generation==generation
        r.command('stop'); finish_without_heartbeat(r)
    finally: r.close()


def test_stop_prevents_remaining_old_episode_outputs(tmp_path):
    r=make(tmp_path)
    try:
        start(r); r.command('stop')
        count=motion_count(r)
        finish_without_heartbeat(r)
        time.sleep(.06)
        assert motion_count(r)==count
        assert r.state=='DISARMED' and r.safety.latched
        assert not r.model_ready
    finally: r.close()


def test_recovery_fault_requires_explicit_fresh_start(tmp_path):
    r=make(tmp_path)
    try:
        r.realtime=False; start(r); r.wait(owner='operator-test')
        r.command('recenter'); r.command('scramble',{'mapping':'reverse_one'})
        r.realtime=True; start(r,'recover')
        r.faults['hide_marker']=True
        finish_without_heartbeat(r)
        assert r.state=='FAULT' and not r.model_ready
        count=motion_count(r); r.faults['hide_marker']=False; r._observe()
        time.sleep(.06)
        assert motion_count(r)==count and not r.safety.active
        r.realtime=False; start(r,'recover'); r.wait(owner='operator-test')
        assert r.state=='READY' and r.model_ready
        assert r.metrics['adapted']['normalized_rmse'] < r.metrics['frozen']['normalized_rmse']*.2
    finally: r.close()


def test_calibration_changes_invalidate_fitted_model(tmp_path,monkeypatch):
    import darwin.runtime as runtime_module
    monkeypatch.setattr(runtime_module,'ROOT',tmp_path)
    r=make(tmp_path)
    try:
        r.realtime=False; start(r); r.wait(owner='operator-test')
        assert r.model_ready
        old_id=r.calibration.calibration_id
        result=r.command('calibration',{'points_px':[[10,10],[629,10],[629,469],[10,469]],'width_m':1.,'height_m':1.,'camera_id':'simulation'})
        assert result['ok'] and r.calibration.calibration_id!=old_id
        assert not r.model_ready and not r.samples and not r.heldout
        assert r.safety.latched
        r.command('target',{'target':[.67,.65]})
        with pytest.raises(ValueError,match='validated model'): start(r,'navigate')
    finally: r.close()

def test_no_motion_cannot_unlock_navigation(tmp_path):
    from darwin.runtime import Runtime
    from darwin.config import Config
    from darwin.types import ActuationReceipt
    r=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path)
    def stalled(action):
        sent=r.env.now;r.env.advance(.42)
        return ActuationReceipt(action.id,1,sent,sent,True)
    r.env.execute=stalled
    try:
        r.command('start-calibration',{'owner_id':'cli'})
        import pytest
        with pytest.raises(RuntimeError,match='insufficient predictable motion'):r.wait()
        assert not r.model_ready and r.state=='FAULT'
    finally:r.close()


def test_successful_episode_clears_stale_monitor_error(tmp_path):
    r=make(tmp_path)
    try:
        r._monitor_error='old tracking fault'
        r.realtime=False
        start(r)
        r.wait(owner='operator-test')
        assert r.snapshot()['error'] is None
    finally:
        r.close()


def test_new_calibration_cycle_clears_stale_target_and_route(tmp_path):
    r=make(tmp_path)
    try:
        r.realtime=False; start(r); r.wait(owner='operator-test')
        r.command('target',{'target':[.65,.65]})
        r.route=[{'x_m':.55,'y_m':.55},{'x_m':.65,'y_m':.65}]
        start(r)
        assert r.target is None and r.route==[] and r.route_index is None
        r.wait(owner='operator-test')
    finally:
        r.close()


@pytest.mark.parametrize('start_pose',[(.14,.5,0),(.86,.5,3.14),(.5,.14,1.57),(.5,.86,-1.57)])
def test_navigation_returns_from_green_buffer_before_resuming_target(tmp_path,start_pose):
    r=make(tmp_path,boundary_margin_m=.10)
    try:
        r.realtime=False; start(r); r.wait(owner='operator-test')
        r.env.reset_pose(*start_pose)
        r.command('target',{'target':[.5,.5]})
        start(r,'navigate'); result=r.wait(owner='operator-test')
        assert result['success']
        assert any(event['kind']=='boundary_recovery_started' for event in r.events)
        assert any(event['kind']=='boundary_recovered' for event in r.events)
        assert r.pose.x_m >= r.config.safe_bounds[0]
    finally:
        r.close()


def test_navigation_near_red_boundary_stops_without_another_motor_action(tmp_path):
    r=make(tmp_path,boundary_margin_m=.10)
    try:
        r.realtime=False; start(r); r.wait(owner='operator-test')
        r.env.reset_pose(.10,.5,0)
        r.command('target',{'target':[.5,.5]})
        count=motion_count(r)
        with pytest.raises(SafetyViolation,match='insufficient red boundary reserve'):
            start(r,'navigate')
        assert motion_count(r)==count and not r.safety.active
    finally:
        r.close()
