"""Privileged differential drive. Never import this module into learning/control."""
import math
import numpy as np

MAPS = {
    'identity':np.eye(2), 'swap':np.array([[0.,1.],[1.,0.]]),
    'reverse_one':np.diag([-1.,1.]), 'reverse_both':-np.eye(2),
    'unequal_gains':np.array([[0.,-.65],[.85,0.]])}

def hidden_mapping(name):
    aliases = {'reverse-one':'reverse_one','reverse-both':'reverse_both','gains':'unequal_gains','unequal-gains':'unequal_gains'}
    name = aliases.get(name,name)
    if name not in MAPS: raise ValueError('unknown scramble')
    return name,MAPS[name].copy()

class DifferentialDrivePlant:
    def __init__(self, seed, variant='linear'):
        self.rng = np.random.default_rng(seed)
        self.pose = np.array([.5,.5,0.])
        self.wheel_speed = np.zeros(2)
        self.wheel_gains = self.rng.uniform(.225,.255,2)
        self.wheelbase = .14
        self.variant = variant
        self.deadband = .14 if variant == 'nonlinear' else 0.
        self.lag_s = .065 if variant == 'nonlinear' else 0.
        self.process_sigma = .0015 if variant in {'noisy','nonlinear'} else 0.

    def step(self, physical, dt):
        p = np.asarray(physical)
        effective = np.sign(p)*np.maximum(np.abs(p)-self.deadband,0)/(1-self.deadband)
        desired = effective*self.wheel_gains
        if self.lag_s: self.wheel_speed += (desired-self.wheel_speed)*(1-math.exp(-dt/self.lag_s))
        else: self.wheel_speed = desired.copy()
        wheels = self.wheel_speed.copy()
        # Process variation happens only while moving; a stopped plant has no propulsion.
        if np.any(np.abs(wheels) > 1e-8): wheels += self.rng.normal(0,self.process_sigma,2)
        v = (wheels[0]+wheels[1])/2; w = (wheels[1]-wheels[0])/self.wheelbase
        half = self.pose[2] + .5*w*dt
        self.pose[0] += v*math.cos(half)*dt; self.pose[1] += v*math.sin(half)*dt
        self.pose[2] = math.atan2(math.sin(self.pose[2]+w*dt),math.cos(self.pose[2]+w*dt))
