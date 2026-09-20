import json
from dataclasses import replace
import numpy as np
import pytest
from darwin.config import Config
from darwin.episodes import transition
from darwin.control.exploration import probe_actions
from darwin.learning.model import MotionModel, evaluate
from darwin.simulation.environment import SimulationEnvironment


def collect(env,seed,count,episode):
    rows = []
    for a in probe_actions(seed,count,env.config.pulse_ms,episode):
        p = env.observe(); receipt=env.execute(a); q=env.observe()
        assert receipt.accepted
        rows.append(transition(a,p,q,env.config.config_id))
    return rows


def test_fit_heldout_checkpoint_and_leakage(tmp_path):
    env=SimulationEnvironment(Config(observation='pose'))
    train=collect(env,7,24,'train'); heldout=collect(env,8,12,'heldout')
    model=MotionModel(); model.fit(train)
    metrics=evaluate(model,heldout)
    assert metrics['normalized_rmse'] < .001
    assert np.array_equal(model.predict([[0,0]]),[[0,0]])
    path=tmp_path/'model.npz'; model.save(path)
    loaded=MotionModel.load(path,env.config.config_id,'simulation')
    assert np.array_equal(model.predict([[.5,-1]]),loaded.predict([[.5,-1]]))
    with pytest.raises(ValueError,match='overlaps'): evaluate(model,train)
    with pytest.raises(ValueError,match='configuration'): MotionModel.load(path,'wrong')
    data=json.loads(path.read_text()); data['measurement_version']='pulse_only'; path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incompatible'): MotionModel.load(path)
    assert not any('map' in name or 'physical' in name for name in train[0].__dict__)


def test_rank_and_bad_data():
    env=SimulationEnvironment(Config(observation='pose'))
    rows=collect(env,1,12,'rank')
    bad=[replace(t,u2=t.u1) for t in rows]
    with pytest.raises(ValueError,match='rank'): MotionModel().fit(bad)
    with pytest.raises(ValueError,match='duplicate'): MotionModel().fit(rows+rows)
    with pytest.raises(ValueError,match='measurement'): MotionModel().fit([replace(t,measurement_version='old') for t in rows])

@pytest.mark.parametrize('seed',[11,22,33,44,55])
@pytest.mark.parametrize('mapping',['swap','reverse_one','reverse_both','unequal_gains'])
def test_real_recovery_heldout(seed,mapping):
    env=SimulationEnvironment(Config(seed=seed,observation='pose',plant_variant='noisy'))
    old=MotionModel(); old.fit(collect(env,seed+1,24,'old'))
    env.scramble(mapping)
    new=MotionModel(); new.fit(collect(env,seed+2,24,'new'))
    heldout=collect(env,seed+3,12,'heldout')
    frozen=evaluate(old,heldout); adapted=evaluate(new,heldout)
    assert adapted['normalized_rmse'] < .2*frozen['normalized_rmse']
