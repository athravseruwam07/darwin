import numpy as np
import pytest
from darwin.config import Config
from darwin.types import RequestedAction
from darwin.simulation.environment import SimulationEnvironment
from darwin.simulation.plant import hidden_mapping

@pytest.mark.parametrize('name',['identity','swap','reverse_one','reverse_both','unequal_gains'])
def test_full_rank_maps_and_zero(name):
    _,matrix=hidden_mapping(name)
    assert np.linalg.matrix_rank(matrix)==2
    assert np.array_equal(matrix@np.zeros(2),np.zeros(2))
    env=SimulationEnvironment(Config()); env.scramble(name)
    before=env.truth_for_renderer(); t=env.now
    receipt=env.execute(RequestedAction('zero',(0.,0.),120))
    assert receipt.accepted and env.now-t==pytest.approx(.42)
    assert env.truth_for_renderer()==before

def test_expected_mapping_semantics():
    for name,expected in [('identity',[.5,-.2]),('swap',[-.2,.5]),('reverse_one',[-.5,-.2]),('reverse_both',[-.5,.2]),('unequal_gains',[.13,.425])]:
        _,matrix=hidden_mapping(name)
        assert matrix@np.array([.5,-.2])==pytest.approx(expected)

def test_faults_and_distinct_timestamps():
    env=SimulationEnvironment(Config())
    first=env.observe(); env.fault('stale_frames',True); env.advance(.2)
    assert env.observe()==first
    env.fault('stale_frames',False); assert env.observe().observed_at > first.observed_at
    env.fault('hide_marker',True); assert not env.observe().valid
    env.fault('disconnect_serial',True)
    p=env.truth_for_renderer(); receipt=env.execute(RequestedAction('a',(1.,1.),120))
    assert not receipt.accepted and env.truth_for_renderer()==p
    env.fault('delayed_observation',True); env.advance(.4)
    assert env.now-env.observe().observed_at >= .25-1e-9

def test_variants_deterministic_and_bounded():
    for variant in ['linear','noisy','nonlinear']:
        a=SimulationEnvironment(Config(plant_variant=variant)); b=SimulationEnvironment(Config(plant_variant=variant))
        for i in range(20):
            action=RequestedAction(str(i),(.6,-.6),120)
            a.execute(action); b.execute(action)
            assert a.observe()==b.observe()
        assert np.isfinite(a.truth_for_renderer()).all()
