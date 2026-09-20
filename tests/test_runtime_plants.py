"""Integrated plant variants and STOP/fitting publication race regression."""
import threading
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
