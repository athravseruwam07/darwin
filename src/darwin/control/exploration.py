"""Balanced independent probes; unknown motion still requires supervisor limits."""
import numpy as np
from darwin.types import RequestedAction

def probe_actions(seed, count, pulse_ms, episode_id):
    if count < 6: raise ValueError('at least six probes required')
    rng = np.random.default_rng(seed)
    # Opposing consecutive pulses bound accumulated drift without knowing the map.
    basis = [(1.,0.),(0.,1.),(1.,1.),(1.,-1.),(.6,0.),(0.,.6),(.6,.6),(.6,-.6)]
    result = []
    while len(result) < count:
        for index in rng.permutation(len(basis)):
            u = np.array(basis[index])*rng.choice([-1.,1.])
            for vector in (u,-u):
                if len(result) == count: break
                result.append(RequestedAction(f'{episode_id}-{len(result):04d}',tuple(float(v) for v in vector),pulse_ms,'bounded-probe-v1',episode_id))
    return result
