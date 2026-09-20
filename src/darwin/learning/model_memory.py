from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MEMORY_VERSION = 1


@dataclass(frozen=True, slots=True)
class ResponseSignature:
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        values = tuple(float(value) for value in self.values)
        if not values or not all(math.isfinite(value) for value in values):
            raise ValueError("signature must contain finite values")
        object.__setattr__(self, "values", values)

    def distance(self, other: "ResponseSignature") -> float:
        if len(self.values) != len(other.values):
            raise ValueError("incompatible signature dimensions")
        scale = max(1.0, math.sqrt(sum(value * value for value in self.values)))
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(self.values, other.values, strict=True))) / scale


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    signature: ResponseSignature
    checkpoint_id: str
    checkpoint_path: str
    validation_metrics: dict[str, float]
    validated: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self); result["signature"] = list(self.signature.values)
        return result


class BodyModelMemory:
    def __init__(self, entries: list[MemoryEntry] | None = None) -> None:
        self.entries = list(entries or [])

    def add(self, signature: ResponseSignature, *, checkpoint_id: str, checkpoint_path: str,
            validation_metrics: dict[str, float], validated: bool) -> MemoryEntry:
        if not checkpoint_id or not checkpoint_path:
            raise ValueError("checkpoint identity and path are required")
        metrics = {str(key): float(value) for key, value in validation_metrics.items()}
        if not all(math.isfinite(value) for value in metrics.values()):
            raise ValueError("metrics must be finite")
        entry = MemoryEntry(signature, checkpoint_id, checkpoint_path, metrics, bool(validated))
        self.entries.append(entry)
        return entry

    def match(self, signature: ResponseSignature, *, max_distance: float) -> MemoryEntry | None:
        if max_distance < 0 or not math.isfinite(max_distance):
            raise ValueError("max distance must be finite and nonnegative")
        valid = [entry for entry in self.entries if entry.validated and len(entry.signature.values) == len(signature.values)]
        if not valid:
            return None
        nearest = min(valid, key=lambda entry: entry.signature.distance(signature))
        return nearest if nearest.signature.distance(signature) <= max_distance else None

    def save(self, path: str | Path) -> None:
        destination = Path(path); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"version": MEMORY_VERSION, "entries": [e.to_dict() for e in self.entries]},
                                          indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BodyModelMemory":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("version") != MEMORY_VERSION or not isinstance(document.get("entries"), list):
            raise ValueError("incompatible model memory")
        memory = cls()
        for raw in document["entries"]:
            memory.add(ResponseSignature(tuple(raw["signature"])), checkpoint_id=raw["checkpoint_id"],
                       checkpoint_path=raw["checkpoint_path"], validation_metrics=raw["validation_metrics"],
                       validated=raw["validated"])
        return memory
