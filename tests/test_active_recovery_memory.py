from __future__ import annotations

import json
import numpy as np
import pytest

from darwin.learning.active_experiments import ActiveExperimentSelector
from darwin.learning.change_detection import ResidualChangeDetector
from darwin.learning.model_memory import BodyModelMemory, ResponseSignature
from darwin.control.exploration import recovery_probe_actions


def test_change_status_is_json_safe_and_requires_consecutive_evidence() -> None:
    detector = ResidualChangeDetector(threshold=0.5, required_exceedances=2, minimum_evidence=3)
    assert not detector.update((0.4, 0.4)).detected
    assert not detector.update((0.6, 0.0)).detected
    status = detector.update((0.8, 0.0))
    assert status.detected and status.consecutive_count == 3 and status.evidence_count == 3
    assert json.loads(json.dumps(status.to_dict()))["detected"] is True


def test_detector_ignores_nonfinite_and_resets_consecutive() -> None:
    detector = ResidualChangeDetector(threshold=0.2, required_exceedances=2)
    assert detector.update(float("nan")).score is None
    detector.update(0.3)
    assert detector.update(0.1).consecutive_count == 0


def test_selector_is_deterministic_filters_pivots_and_finds_uncertainty() -> None:
    candidates = [(0.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.7, 0.7), (0.7, -0.7), (-0.7, 0.7)]
    observed = np.asarray([(1.0, 1.0), (0.8, 0.8), (-1.0, -1.0), (-0.8, -0.8)])
    first = ActiveExperimentSelector(seed=9).choose(candidates, observed)
    second = ActiveExperimentSelector(seed=9).choose(candidates, observed)
    assert first == second and first in {(0.7, -0.7), (-0.7, 0.7)}
    assert first[0] != 0 and first[1] != 0


def test_model_memory_json_roundtrip_matches_validated_only(tmp_path) -> None:
    memory = BodyModelMemory()
    memory.add(ResponseSignature((0.05, 0.8, 0.04, -0.7)), checkpoint_id="model-a",
               checkpoint_path="checkpoints/a.npz", validation_metrics={"yaw_mae": 0.02}, validated=True)
    memory.add(ResponseSignature((-0.03, -0.5, 0.06, 0.4)), checkpoint_id="bad",
               checkpoint_path="checkpoints/b.npz", validation_metrics={}, validated=False)
    assert memory.match(ResponseSignature((0.051, 0.79, 0.041, -0.69)), max_distance=0.05).checkpoint_id == "model-a"
    assert memory.match(ResponseSignature((-0.03, -0.5, 0.06, 0.4)), max_distance=0.01) is None
    path = tmp_path / "memory.json"; memory.save(path)
    assert BodyModelMemory.load(path).match(ResponseSignature((0.05, 0.8, 0.04, -0.7)), max_distance=0.001)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_invalid_inputs_fail_closed() -> None:
    with pytest.raises(ValueError):
        ResponseSignature((1.0, float("inf")))
    with pytest.raises(ValueError):
        ActiveExperimentSelector(seed=1).choose([(0.0, 0.0), (1.0, 0.0)], [])


def test_recovery_probes_cover_straight_and_turn_at_both_power_levels() -> None:
    actions = recovery_probe_actions(seed=17, count=8, pulse_ms=120, episode_id="heldout")
    vectors = [action.u for action in actions]
    assert set(vectors) == {
        (1.0, 1.0), (-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0),
        (0.6, 0.6), (-0.6, -0.6), (0.6, -0.6), (-0.6, 0.6),
    }
    assert len({action.id for action in actions}) == len(actions)
    assert all(action.episode_id == "heldout" for action in actions)


def test_active_recovery_probes_do_not_repeat_before_candidate_exhaustion() -> None:
    actions = recovery_probe_actions(
        seed=23,
        count=12,
        pulse_ms=120,
        episode_id="training",
        candidate_levels=(-1.0, -0.6, 0.0, 0.6, 1.0),
        active=True,
    )
    vectors = [action.u for action in actions]
    assert len(vectors) == len(set(vectors)) == 12
    assert all(left != 0 and right != 0 for left, right in vectors)
    assert {(1.0, 1.0), (1.0, -1.0), (0.6, 0.6), (0.6, -0.6)} <= set(vectors)


def test_recovery_probe_validation_rejects_undercovered_schedule() -> None:
    with pytest.raises(ValueError, match="at least eight"):
        recovery_probe_actions(seed=1, count=6, pulse_ms=120, episode_id="too-short")
