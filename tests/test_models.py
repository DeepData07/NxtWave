from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import ensure_run_directory
from models import EXPECTED_GATE_IDS, GateResult, LearnerProfile, SemanticEvaluation


def make_gate(gate_id: str, passed: bool = True) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "name": f"Gate {gate_id}",
        "passed": passed,
        "evidence": "Lesson evidence",
        "reason": "Evaluation reason",
        "required_fix": "Required fix",
    }


def test_default_learner_profile_matches_assignment() -> None:
    learner = LearnerProfile()

    assert learner.region == "India"
    assert learner.technical_background == "none"
    assert learner.goal == "start an AI career"


def test_semantic_evaluation_requires_each_gate_once() -> None:
    evaluation = SemanticEvaluation(gates=[make_gate(gate_id) for gate_id in sorted(EXPECTED_GATE_IDS)])

    assert evaluation.overall_pass is True


def test_semantic_evaluation_rejects_duplicate_gate() -> None:
    duplicated_gates = [make_gate(gate_id) for gate_id in sorted(EXPECTED_GATE_IDS)]
    duplicated_gates[-1] = make_gate("R1")

    with pytest.raises(ValidationError, match="exactly once"):
        SemanticEvaluation(gates=duplicated_gates)


def test_overall_pass_is_recomputed_from_gate_results() -> None:
    gates = [make_gate(gate_id) for gate_id in sorted(EXPECTED_GATE_IDS)]
    gates[2] = make_gate("R3", passed=False)

    assert SemanticEvaluation(gates=gates).overall_pass is False


def test_run_directory_helper_creates_safe_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")

    run_directory = ensure_run_directory("run_20260904_001")

    assert run_directory.is_dir()


def test_run_directory_helper_rejects_path_like_identifier() -> None:
    with pytest.raises(ValueError, match="filename-safe"):
        ensure_run_directory("../outside")
