from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ChangeStatus:
    score: float | None
    threshold: float
    detected: bool
    consecutive_count: int
    evidence_count: int

    def to_dict(self) -> dict[str, float | int | bool | None]:
        return asdict(self)


class ResidualChangeDetector:
    """Sequential pre-update residual detector; invalid tracking is ignored."""

    def __init__(self, *, threshold: float, required_exceedances: int = 3,
                 minimum_evidence: int | None = None, window_size: int | None = None) -> None:
        minimum = required_exceedances if minimum_evidence is None else minimum_evidence
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("threshold must be finite and positive")
        if required_exceedances < 1 or minimum < required_exceedances:
            raise ValueError("minimum evidence must cover required exceedances")
        if window_size is not None and window_size < required_exceedances:
            raise ValueError("window cannot be shorter than required exceedances")
        self.threshold, self.required_exceedances = threshold, required_exceedances
        self.minimum_evidence, self.evidence_count, self.consecutive_count = minimum, 0, 0

    def update(self, residual: float | Iterable[float], *, observation_valid: bool = True) -> ChangeStatus:
        score = self._score(residual) if observation_valid else None
        if score is None:
            return self.status(None)
        self.evidence_count += 1
        self.consecutive_count = self.consecutive_count + 1 if score > self.threshold else 0
        return self.status(score)

    def status(self, score: float | None = None) -> ChangeStatus:
        detected = self.evidence_count >= self.minimum_evidence and self.consecutive_count >= self.required_exceedances
        return ChangeStatus(score, self.threshold, detected, self.consecutive_count, self.evidence_count)

    def reset(self) -> None:
        self.evidence_count = self.consecutive_count = 0

    @staticmethod
    def _score(residual: float | Iterable[float]) -> float | None:
        if isinstance(residual, (int, float)):
            value = abs(float(residual))
            return value if math.isfinite(value) else None
        try:
            values = tuple(float(value) for value in residual)
        except (TypeError, ValueError):
            return None
        if not values or not all(math.isfinite(value) for value in values):
            return None
        return math.sqrt(sum(value * value for value in values))
