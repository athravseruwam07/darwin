"""Grid search over learned forward predictions; no simulator imports."""
import itertools
import math
import uuid
import numpy as np
from darwin.types import RequestedAction
from .rollout import rollout, swept_safe, wrap

def obstacle_safe(path, obstacles, padding=0.):
    for obstacle in obstacles or []:
        center=obstacle.get('center_m') if isinstance(obstacle,dict) else None
        x=obstacle.get('x_m',center[0] if center else None) if isinstance(obstacle,dict) else None
        y=obstacle.get('y_m',center[1] if center else None) if isinstance(obstacle,dict) else None
        radius=obstacle.get('radius_m') if isinstance(obstacle,dict) else None
        if not np.isfinite([x,y,radius]).all() or radius<0: continue
        if any(math.hypot(float(px)-x,float(py)-y)<=radius+padding for px,py,*_ in path): return False
    return True

def boundary_violation(x, y, bounds):
    left,right,bottom,top=bounds
    return max(left-x,0.)+max(x-right,0.)+max(bottom-y,0.)+max(y-top,0.)

def boundary_clearance(x, y, bounds):
    left,right,bottom,top=bounds
    return min(x-left,right-x,y-bottom,top-y)

class Policy:
    def __init__(self, config):
        self.config = config
        self.previous = np.zeros(2)
        self.last_path = []
        self.last_prediction = None

    def choose(self, pose, target, model, safety_context=None):
        if not pose.valid or model.model_id is None: return None
        if model.calibration_id != pose.calibration_id or model.config_id != self.config.config_id: return None
        if not np.isfinite([pose.x_m,pose.y_m,pose.theta_rad,*target]).all(): return None
        if safety_context and (safety_context.get('stale_model') or safety_context.get('inhibited')): return None
        c = self.config
        recovery_bounds=(safety_context or {}).get('recovery_bounds')
        dx,dy = target[0]-pose.x_m,target[1]-pose.y_m
        distance = math.hypot(dx,dy)
        if distance <= c.goal_contact_radius_m and not recovery_bounds: return None
        bearing = math.atan2(dy,dx)
        error = wrap(bearing-pose.theta_rad)
        # Reverse travel is equally valid; reduces needless rotations and budgets.
        direction = 1.
        if abs(error) > math.pi/2:
            direction = -1.; error = wrap(error-math.copysign(math.pi,error))
        desired_v = direction*min(c.desired_max_speed_mps, .8*distance)*max(0.,math.cos(error))**3
        if abs(error) > .8: desired_v = 0.
        desired_w = float(np.clip(2.3*error,-c.desired_max_yaw_radps,c.desired_max_yaw_radps))
        actions = np.array([
            action for action in itertools.product(c.candidate_levels, repeat=2)
            if action[0] != 0 and action[1] != 0
        ])
        predictions = model.predict(actions)
        duration = (c.pulse_ms+c.settle_ms)/1000
        allowed_bounds=(safety_context or {}).get('bounds',c.safe_bounds)
        physical_bounds=(safety_context or {}).get('physical_bounds',c.physical_bounds)
        start_violation=boundary_violation(pose.x_m,pose.y_m,recovery_bounds) if recovery_bounds else 0.
        start_clearance=boundary_clearance(pose.x_m,pose.y_m,physical_bounds)
        best = None
        for action,pred in zip(actions,predictions):
            v,w = pred
            if abs(v) > c.desired_max_speed_mps*1.4 or abs(w) > c.desired_max_yaw_radps*1.8: continue
            path = rollout(pose,v,w,duration)
            if not swept_safe(path,allowed_bounds): continue
            if safety_context and not obstacle_safe(path,safety_context.get('obstacles'),safety_context.get('obstacle_padding_m',0.)): continue
            endpoint = path[-1]
            if recovery_bounds:
                endpoint_clearance=boundary_clearance(endpoint[0],endpoint[1],physical_bounds)
                endpoint_violation=boundary_violation(endpoint[0],endpoint[1],recovery_bounds)
                translation=abs(float(v))*duration
                if endpoint_clearance < start_clearance-1e-6: continue
                if translation>.003 and endpoint_violation >= start_violation-1e-4: continue
            remaining = math.hypot(target[0]-endpoint[0],target[1]-endpoint[1])
            score = ((v-desired_v)/c.desired_max_speed_mps)**2 + .8*((w-desired_w)/c.desired_max_yaw_radps)**2
            score += .015*float(action@action) + .005*float(np.sum((action-self.previous)**2))
            score += .5*(remaining-distance)/max(c.desired_max_speed_mps*duration,.001)
            if recovery_bounds:
                score += 4*endpoint_violation/max(c.boundary_margin_m,.001)
            if best is None or score < best[0]: best = (score,action,path,pred)
        if best is None or np.all(best[1] == 0): return None
        _, action,path,pred = best
        self.previous = action.copy(); self.last_path = path.tolist(); self.last_prediction = np.asarray(pred).tolist()
        return RequestedAction(uuid.uuid4().hex,tuple(action.tolist()),c.pulse_ms,'learned-grid-v1','navigation')
