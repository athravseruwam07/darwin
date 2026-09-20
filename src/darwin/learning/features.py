"""Public abstract action features; deliberately no actuator dependency."""
import numpy as np
from darwin.types import FEATURE_VERSION

FEATURE_ORDER = ['u1', 'u2', 'bias']

def features(actions):
    a = np.asarray(actions, dtype=float)
    if a.ndim == 1: a = a.reshape(1, -1)
    if a.ndim != 2 or a.shape[1] != 2 or not np.isfinite(a).all():
        raise ValueError('actions must be a finite Nx2 array')
    if np.any(np.abs(a) > 1 + 1e-10): raise ValueError('abstract action outside [-1,1]')
    return np.column_stack((a, np.ones(len(a))))
