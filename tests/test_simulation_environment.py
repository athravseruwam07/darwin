import numpy as np
import pytest
from darwin.config import Config
from darwin.types import RequestedAction
from darwin.simulation.environment import SimulationEnvironment
from darwin.simulation.plant import hidden_mapping

@pytest.mark.parametrize('name',['identity','swap','reverse_left','reverse_right','reverse_both','unequal_gains'])
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
    for name,expected in [('identity',[.5,-.2]),('swap',[-.2,.5]),('reverse_left',[-.5,-.2]),('reverse_right',[.5,.2]),('reverse_both',[-.5,.2]),('unequal_gains',[.13,.425])]:
        _,matrix=hidden_mapping(name)
        assert matrix@np.array([.5,-.2])==pytest.approx(expected)


def test_legacy_reverse_one_aliases_reverse_left():
    _, legacy = hidden_mapping('reverse_one')
    _, explicit = hidden_mapping('reverse_left')
    assert np.array_equal(legacy, explicit)

def test_shared_weak_wheel_name_is_supported():
    name, mapping = hidden_mapping('weaken_left')
    assert name == 'unequal_gains'
    assert mapping.shape == (2, 2)

def test_random_mashup_is_seeded_full_rank_and_private():
    first=SimulationEnvironment(Config(seed=91)); second=SimulationEnvironment(Config(seed=91))
    first.mutate('random_mashup'); second.mutate('random_mashup')
    action=RequestedAction('probe',(.6,-.4),120)
    first.execute(action); second.execute(action)
    assert first.truth_for_renderer()==second.truth_for_renderer()
    assert first.audit_records[-1]['map_name']=='random_mashup'
    recipe=first.audit_records[-2]['recipe']
    assert len(recipe)>=2

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
