"""Substepped constant-average-twist rollout with swept footprint constraints."""
import math
import numpy as np

def wrap(angle): return math.atan2(math.sin(angle),math.cos(angle))

def rollout(pose, v, omega, duration, steps=20):
    if duration <= 0 or steps < 2: raise ValueError('invalid rollout horizon')
    x,y,theta = pose.x_m,pose.y_m,pose.theta_rad
    path = [(x,y,theta)]
    dt = duration/steps
    for _ in range(steps):
        half = theta + omega*dt/2
        x += v*math.cos(half)*dt; y += v*math.sin(half)*dt
        theta = wrap(theta+omega*dt)
        path.append((x,y,theta))
    return np.array(path)

def swept_safe(path, bounds, extra_margin=0.):
    xmin,xmax,ymin,ymax = bounds
    p = np.asarray(path)
    return bool(np.isfinite(p).all() and np.all((p[:,0] >= xmin+extra_margin)&(p[:,0] <= xmax-extra_margin)&(p[:,1] >= ymin+extra_margin)&(p[:,1] <= ymax-extra_margin)))
