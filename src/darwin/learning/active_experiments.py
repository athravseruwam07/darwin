from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
import numpy as np
from numpy.typing import NDArray


class ActiveExperimentSelector:
    """Chooses probes using action-space uncertainty, never plant truth or outputs."""

    def __init__(self, *, seed: int, regularization: float = 1e-6) -> None:
        if regularization <= 0 or not math.isfinite(regularization):
            raise ValueError("regularization must be finite and positive")
        self.seed, self.regularization = seed, regularization

    def choose(self, candidates: Sequence[tuple[float, float]],
               observed_actions: NDArray[np.floating] | Iterable[tuple[float, float]]) -> tuple[float, float]:
        allowed = self._allowed(candidates)
        observed = np.asarray(list(observed_actions), dtype=np.float64)
        if observed.size == 0:
            observed = np.empty((0, 2), dtype=np.float64)
        if observed.ndim != 2 or observed.shape[1] != 2 or not np.all(np.isfinite(observed)):
            raise ValueError("observed actions must be finite N x 2")
        information = observed.T @ observed + self.regularization * np.eye(2)
        scores = [float(np.asarray(action) @ np.linalg.solve(information, np.asarray(action))) for action in allowed]
        maximum = max(scores)
        ties = [action for action, score in zip(allowed, scores, strict=True)
                if math.isclose(score, maximum, rel_tol=1e-12, abs_tol=1e-12)]
        return random.Random(self.seed).choice(sorted(ties))

    @staticmethod
    def _allowed(candidates: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        allowed: list[tuple[float, float]] = []
        for raw in candidates:
            if len(raw) != 2 or not all(math.isfinite(value) and -1 <= value <= 1 for value in raw):
                raise ValueError("candidates must be finite pairs within [-1, 1]")
            action = (float(raw[0]), float(raw[1]))
            if action[0] != 0 and action[1] != 0 and action not in allowed:
                allowed.append(action)
        if not allowed:
            raise ValueError("no nonzero two-motor candidates remain")
        return allowed
