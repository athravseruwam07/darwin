import math
import pytest
from darwin.config import Config
from darwin.types import Pose
from darwin.learning.model import MotionModel
from darwin.control.policy import Policy
from darwin.control.rollout import rollout,swept_safe
from darwin.simulation.environment import SimulationEnvironment
from test_learning_model import collect

@pytest.mark.parametrize('seed',[11,22,33,44,55])
@pytest.mark.parametrize('mapping',['identity','swap','reverse_one','reverse_both','unequal_gains'])
def test_learned_navigation(seed,mapping):
    c=Config(seed=seed,observation='pose'); env=SimulationEnvironment(c); env.scramble(mapping)
    model=MotionModel(); model.fit(collect(env,seed,24,'train'))
    # An explicit between-trial reset, never a within-trial teleport.
    env.reset_pose(.5,.5,0)
    policy=Policy(c); target=(.67,.65)
    for step in range(c.max_episode_actions):
        pose=env.observe()
        if math.hypot(pose.x_m-target[0],pose.y_m-target[1])<=c.goal_radius_m: break
        action=policy.choose(pose,target,model)
        assert action is not None
        env.execute(action)
        assert swept_safe([[env.observe().x_m,env.observe().y_m,0]],c.safe_bounds)
    pose=env.observe()
    assert math.hypot(pose.x_m-target[0],pose.y_m-target[1])<=c.goal_radius_m
    assert env.now <= 1+24*.42+c.max_episode_seconds+.01


def test_swept_arc_rejects_endpoint_safe_curve():
    pose=Pose(1,0,.5,.5,0)
    path=rollout(pose,.2,2*math.pi,1,100)
    assert swept_safe(path[[0,-1]],(.45,.55,.45,.55))
    assert not swept_safe(path,(.45,.55,.45,.55))
