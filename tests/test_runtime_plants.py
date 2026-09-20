"""Integrated plant variants and STOP/fitting publication race regression."""
import threading
import time
import pytest
from darwin.config import Config
from darwin.runtime import Runtime

@pytest.mark.parametrize('variant',['linear','noisy','nonlinear'])
@pytest.mark.parametrize('observation',['pose','vision'])
def test_runtime_complete_cycle_variants(tmp_path,variant,observation):
    r=Runtime(Config(seed=33,plant_variant=variant,observation=observation),realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'cli'}); r.wait()
        assert r.model_ready and len(r.samples)==24 and len(r.heldout)==12
        r.command('recenter'); r.command('target',{'target':[.67,.65]})
        r.command('navigate',{'owner_id':'cli'}); before=r.wait()
        assert before['success'] and before['elapsed_s']>=before['actions']*.42+.49
        r.command('recenter'); r.command('scramble',{'mapping':'reverse_one'})
        assert not r.model_ready
        r.command('recover',{'owner_id':'cli'}); r.wait()
        metrics=r.snapshot()['validation_metrics']
        assert metrics['adapted']['normalized_rmse'] < metrics['frozen']['normalized_rmse']*.2
        r.command('recenter'); r.command('target',{'target':[.32,.68]})
        r.command('navigate',{'owner_id':'cli'}); after=r.wait()
        assert after['success']
    finally: r.close()


def test_stop_during_evaluation_cannot_publish_ready(tmp_path,monkeypatch):
    import darwin.learning.model as module
    entered=threading.Event(); release=threading.Event()
    original=module.evaluate
    def blocked(*args,**kwargs):
        result=original(*args,**kwargs)
        entered.set(); assert release.wait(5)
        return result
    monkeypatch.setattr(module,'evaluate',blocked)
    r=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'cli'})
        assert entered.wait(5)
        r.command('stop'); release.set()
        r._job.join(5)
        assert not r.busy
        assert r.state=='DISARMED'
        assert r.safety.latched and not r.safety.active
    finally:
        release.set(); r.close()


def test_actuator_mutation_does_not_notify_or_reset_learner(tmp_path):
    r=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path/'runs')
    try:
        generation=r.safety.start('operator',r.now)
        r.recovery_phase='navigating with baseline model'
        r.change_detector.update((.05,.05))
        before=r.change_detector.status().to_dict()
        r._pending_mutations=[('reverse_left','secret-change')]

        r._apply_pending_mutations(generation)

        assert r.recovery_phase=='navigating with baseline model'
        assert r.change_detector.status().to_dict()==before
        assert r.frozen_model is None
        assert not any(event['kind']=='mutation_injected' for event in r.events)
        assert any(record.get('kind')=='mutation' for record in r.actuator.audit_records)
    finally:
        r.close()


@pytest.mark.parametrize('mapping',['reverse_right','random_mashup'])
def test_adaptation_challenge_detects_reversal_recovers_and_finishes(tmp_path,mapping):
    config=Config(observation='pose',mismatch_required_exceedances=2)
    r=Runtime(config,realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'challenge'}); r.wait(owner='challenge')
        original_model_id=r.model.model_id
        r.command('recenter',{'x_m':.5,'y_m':.5,'theta_rad':0})
        r.command('target',{'target':[.68,.65]})

        result=r.command('adaptation-challenge',{'owner_id':'challenge','mapping':mapping})
        assert result['ok'] and result['mutation']=='hidden'
        navigation=r.wait(owner='challenge')

        assert navigation['success'] and r.state=='GOAL'
        assert r.model.model_id != original_model_id
        assert r.metrics['adapted']['normalized_rmse'] < r.metrics['frozen']['normalized_rmse']
        mismatch=next(event for event in r.events if event['kind']=='model_mismatch')
        assert mismatch['source']=='camera_prediction_residual'
        assert mismatch['privileged_mutation_signal'] is False
        assert 'mutation' not in mismatch
        assert r.snapshot()['body_change_signal']['kind']=='body_model_mismatch'
        assert r.snapshot()['model_memory']['count'] >= 2
        assert r.snapshot()['change_detection']['detected']
        assert r.snapshot()['adaptation_complete'] is True
    finally:
        r.close()


@pytest.mark.parametrize('mapping',['reverse_left','reverse_right','reverse_both','swap','weaken_left','random_mashup'])
def test_operator_mutation_during_navigation_auto_recovers_without_disclosure(tmp_path,mapping):
    r=Runtime(Config(observation='pose',mismatch_required_exceedances=2),realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'operator'}); r.wait(owner='operator')
        original_model_id=r.model.model_id
        r.command('recenter'); r.command('target',{'target':[.7,.68]})
        r.realtime=True
        r.command('navigate',{'owner_id':'operator'})
        deadline=time.monotonic()+3
        while r.state!='NAVIGATING' and time.monotonic()<deadline: time.sleep(.005)
        response=r.command('inject-mutation',{'mapping':mapping,'owner_id':'operator'})
        assert response['ok'] and set(response)=={'ok','change_id','queued'}
        assert mapping not in str(response)
        navigation=r.wait(owner='operator',timeout=30)
        assert navigation['success'] and r.model.model_id!=original_model_id
        assert r.metrics['adapted']['normalized_rmse'] < r.metrics['frozen']['normalized_rmse']
    finally: r.close()


def test_repeated_active_mutations_queue_safely(tmp_path):
    r=Runtime(Config(observation='pose',mismatch_required_exceedances=2),realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'operator'}); r.wait(owner='operator')
        r.command('recenter'); r.command('target',{'target':[.7,.68]}); r.realtime=True
        r.command('navigate',{'owner_id':'operator'})
        deadline=time.monotonic()+3
        while r.state!='NAVIGATING' and time.monotonic()<deadline: time.sleep(.005)
        responses=[r.command('inject-mutation',{'mapping':name,'owner_id':'operator'}) for name in ('reverse_left','swap','random_mashup')]
        assert len({item['change_id'] for item in responses})==3
        result=r.wait(owner='operator',timeout=30)
        assert result['success'] and r.state=='GOAL'
    finally: r.close()


def test_live_mutation_requires_owner_gate_and_stop_clears_queue(tmp_path):
    r=Runtime(Config(observation='pose'),realtime=False,run_root=tmp_path/'runs')
    try:
        r.command('start-calibration',{'owner_id':'operator'}); r.wait(owner='operator')
        r.command('recenter'); r.command('target',{'target':[.7,.68]}); r.realtime=True
        r.command('navigate',{'owner_id':'operator'})
        deadline=time.monotonic()+3
        while r.state!='NAVIGATING' and time.monotonic()<deadline: time.sleep(.005)
        with pytest.raises(ValueError,match='owner'): r.command('inject-mutation',{'mapping':'swap','owner_id':'intruder'})
        r.command('inject-mutation',{'mapping':'swap','owner_id':'operator'})
        r.command('stop')
        assert not r._pending_mutations
    finally: r.close()


def test_hardware_live_mutation_defaults_disabled(tmp_path):
    config=Config(mode='hardware',camera_backend='oak')
    assert config.live_mutation_enabled is False
