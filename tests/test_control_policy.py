import math
import numpy as np
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
        if math.hypot(pose.x_m-target[0],pose.y_m-target[1])<=c.goal_contact_radius_m: break
        action=policy.choose(pose,target,model)
        assert action is not None
        env.execute(action)
        assert swept_safe([[env.observe().x_m,env.observe().y_m,0]],c.safe_bounds)
    pose=env.observe()
    assert math.hypot(pose.x_m-target[0],pose.y_m-target[1])<=c.goal_contact_radius_m
    assert env.now <= 1+24*.42+c.max_episode_seconds+.01


def test_swept_arc_rejects_endpoint_safe_curve():
    pose=Pose(1,0,.5,.5,0)
    path=rollout(pose,.2,2*math.pi,1,100)
    assert swept_safe(path[[0,-1]],(.45,.55,.45,.55))
    assert not swept_safe(path,(.45,.55,.45,.55))


def test_policy_excludes_single_wheel_pivots_that_stall_under_load():
    config = Config()
    pose = Pose(1, 0, .5, .5, 0, calibration_id="simulation")

    class RecordingModel:
        model_id = "recording"
        config_id = config.config_id
        calibration_id = pose.calibration_id

        def predict(self, actions):
            self.actions = actions
            return [[0.0, 0.0] for _ in actions]

    model = RecordingModel()
    Policy(config).choose(pose, (.65, .65), model)

    assert all((left == 0) == (right == 0) for left, right in model.actions)


def test_policy_finishes_when_robot_footprint_touches_point_target():
    config=Config(robot_radius_m=.08,goal_radius_m=.06)
    pose=Pose(1,0,.5,.5,0,calibration_id='simulation')

    class ReadyModel:
        model_id='ready'; config_id=config.config_id; calibration_id=pose.calibration_id

    assert math.hypot(.575-pose.x_m,.5-pose.y_m)>config.goal_radius_m
    assert Policy(config).choose(pose,(.575,.5),ReadyModel()) is None


def test_policy_rejects_predicted_paths_through_camera_obstacles():
    config=Config()
    pose=Pose(1,0,.5,.5,0,calibration_id='simulation')

    class DifferentialModel:
        model_id='differential'; config_id=config.config_id; calibration_id=pose.calibration_id
        def predict(self,actions):
            values=[]
            for left,right in actions:
                values.append([.05*(left+right),.5*(right-left)])
            return np.asarray(values)

    model=DifferentialModel(); obstacle={'x_m':.53,'y_m':.5,'radius_m':.008}
    action=Policy(config).choose(pose,(.7,.5),model,{'obstacles':[obstacle]})
    assert action is not None
    v,w=model.predict([action.u])[0]
    path=rollout(pose,v,w,(config.pulse_ms+config.settle_ms)/1000)
    assert min(math.hypot(x-obstacle['x_m'],y-obstacle['y_m']) for x,y,_ in path)>obstacle['radius_m']


def test_policy_can_choose_strictly_inward_recovery_inside_physical_boundary():
    config=Config(boundary_margin_m=.10,robot_radius_m=.08)
    pose=Pose(1,0,.14,.5,0,calibration_id='simulation')

    class DifferentialModel:
        model_id='differential'; config_id=config.config_id; calibration_id=pose.calibration_id
        def predict(self,actions):
            return np.asarray([[.04*(left+right),.5*(right-left)] for left,right in actions])

    model=DifferentialModel()
    action=Policy(config).choose(pose,(.5,.5),model,{
        'bounds':config.boundary_recovery_bounds,
        'recovery_bounds':config.safe_bounds,
        'physical_bounds':config.physical_bounds,
    })
    assert action is not None
    v,w=model.predict([action.u])[0]
    path=rollout(pose,v,w,(config.pulse_ms+config.settle_ms)/1000)
    assert swept_safe(path,config.boundary_recovery_bounds)
    assert path[-1,0] > pose.x_m
