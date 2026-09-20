"""Balanced independent probes; unknown motion still requires supervisor limits."""
import itertools
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


def recovery_probe_actions(seed, count, pulse_ms, episode_id, *,
                           candidate_levels=(-1., -.6, 0., .6, 1.), active=False):
    """Return recovery trials with guaranteed straight/turn excitation.

    Hardware deadband makes a corner-only fit and pivot-only validation set
    misleading. The first eight trials always cover signed straight and turn
    responses at full and moderate power. Additional active trials maximize
    action-space information without repeating a vector until candidates are
    exhausted.
    """
    if count < 8:
        raise ValueError('recovery validation requires at least eight probes')
    if pulse_ms <= 0:
        raise ValueError('pulse duration must be positive')
    core = [
        (1., 1.), (-1., -1.), (1., -1.), (-1., 1.),
        (.6, .6), (-.6, -.6), (.6, -.6), (-.6, .6),
    ]
    levels = tuple(float(value) for value in candidate_levels)
    if not all(np.isfinite(levels)) or any(abs(value) > 1 for value in levels):
        raise ValueError('candidate levels must be finite and within [-1, 1]')
    candidates = [tuple(map(float, vector)) for vector in itertools.product(levels, repeat=2)
                  if vector[0] != 0 and vector[1] != 0]
    if not set(core).issubset(candidates):
        raise ValueError('candidate levels must include -1, -0.6, 0.6, and 1')

    vectors = list(core[:count])
    remaining = [vector for vector in candidates if vector not in vectors]
    observed = list(vectors)
    rng = np.random.default_rng(seed)
    selector = None
    if active:
        from darwin.learning.active_experiments import ActiveExperimentSelector
        selector = ActiveExperimentSelector(seed=seed)

    while len(vectors) < count:
        if not remaining:
            remaining = list(candidates)
        chosen = selector.choose(remaining, observed) if selector else remaining[int(rng.integers(len(remaining)))]
        pair = (chosen, (-chosen[0], -chosen[1]))
        for vector in pair:
            if len(vectors) >= count:
                break
            if vector not in remaining:
                continue
            vectors.append(vector)
            observed.append(vector)
            remaining.remove(vector)

    policy_id = 'active-information-v2' if active else 'stratified-heldout-v2'
    return [RequestedAction(f'{episode_id}-{index:04d}', vector, pulse_ms, policy_id, episode_id)
            for index, vector in enumerate(vectors)]
