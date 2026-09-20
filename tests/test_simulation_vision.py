"""Learning and navigation consume actual detected pixels, never truth poses."""
import math
import pytest
from darwin.config import Config
from darwin.episodes import transition
from darwin.control.exploration import probe_actions
from darwin.control.policy import Policy
from darwin.learning.model import MotionModel,evaluate
from darwin.simulation.environment import SimulationEnvironment
from darwin.vision.calibration import Calibration
from darwin.vision.markers import render_frame
from darwin.vision.tracking import Tracker

@pytest.mark.parametrize('seed,mapping',[(11,'swap'),(22,'reverse_one'),(33,'unequal_gains')])
def test_pixels_to_learning_to_navigation(seed,mapping):
    c=Config(seed=seed); env=SimulationEnvironment(c)
    calibration=Calibration.from_corners([[50,40],[590,40],[590,440],[50,440]],1.,1.,(640,480))
    tracker=Tracker(); frame_id=0
    def observe():
        nonlocal frame_id
        frame_id+=1
        # Only renderer gets the privileged pose. Learner gets detector output.
        frame=render_frame(*env.truth_for_renderer(),calibration,frame_id,env.now)
        pose=tracker.observe(frame,calibration)
        assert pose.valid
        return pose
    def collect(seed,episode,count=24):
        rows=[]
        for action in probe_actions(seed,count,c.pulse_ms,episode):
            start=observe(); env.execute(action); end=observe()
            rows.append(transition(action,start,end,c.config_id))
        return rows
    old=MotionModel(); old.fit(collect(seed,'before'))
    env.scramble(mapping)
    adapted=MotionModel(); adapted.fit(collect(seed+1,'adapt'))
    heldout=collect(seed+2,'heldout',12)
    assert evaluate(adapted,heldout)['normalized_rmse'] < evaluate(old,heldout)['normalized_rmse']*.2
    env.reset_pose(.5,.5,0)
    policy=Policy(c); target=(.67,.65)
    for _ in range(c.max_episode_actions):
        pose=observe()
        if math.hypot(pose.x_m-target[0],pose.y_m-target[1])<=c.goal_contact_radius_m: break
        action=policy.choose(pose,target,adapted)
        assert action is not None
        env.execute(action)
    else: pytest.fail('navigation action budget exhausted')
