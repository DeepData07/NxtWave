from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from config import Settings
from evaluation import (
    SemanticEvaluationError,
    build_failure_packet,
    run_semantic_evaluation,
    semantic_evaluation_schema,
    validate_gate_set,
)
from models import LearnerProfile
from tests.rag_facts_fixture import local_rag_facts


GATE_NAMES = {
    "R1": "Factual Accuracy",
    "R2": "Essential Coverage",
    "R3": "Beginner Accessibility",
    "R4": "Jargon Explainability",
    "R5": "Learning by Example",
    "R6": "Teaching Flow",
    "R7": "Appropriate Depth",
    "R8": "Standalone and Complete",
}


def settings() -> Settings:
    return Settings(
        together_api_key="test-key",
        tavily_api_key=None,
        fast_model="fast-model",
        generator_model="generator-model",
        evaluator_model="evaluator-model",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=50,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=200,
    )


def semantic_payload(*failed_gate_ids: str) -> dict[str, object]:
    failed = set(failed_gate_ids)
    return {
        "gates": [
            {
                "gate_id": gate_id,
                "name": GATE_NAMES[gate_id],
                "passed": gate_id not in failed,
                "evidence": f"Evidence for {gate_id}",
                "reason": "A requirement is not met." if gate_id in failed else "Requirement met.",
                "required_fix": "Make the required improvement."
                if gate_id in failed
                else "No change needed.",
            }
            for gate_id in GATE_NAMES
        ]
    }


def fake_client_for(*payloads: dict[str, object]) -> object:
    responses = iter(payloads)

    class FakeCompletions:
        def create(self, **request: object) -> object:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(responses))))
                ]
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))


@pytest.mark.parametrize(
    ("lesson", "failed_gate"),
    [
        ("RAG retrains the model weights for every question.", "R1"),
        ("Embeddings are used without any explanation.", "R4"),
        ("RAG is helpful. No walkthrough is provided.", "R5"),
    ],
)
def test_semantic_failures_create_targeted_failure_packets(
    lesson: str, failed_gate: str
) -> None:
    evaluation = run_semantic_evaluation(
        lesson,
        LearnerProfile(),
        local_rag_facts(),
        settings=settings(),
        client=fake_client_for(semantic_payload(failed_gate)),
    )
    packet = build_failure_packet(0, evaluation)

    assert evaluation.overall_pass is False
    assert packet is not None
    assert [gate.gate_id for gate in packet.failed_gates] == [failed_gate]


def test_strong_lesson_has_a_path_to_all_eight_passes() -> None:
    evaluation = run_semantic_evaluation(
        "A complete grounded lesson.",
        LearnerProfile(),
        local_rag_facts(),
        settings=settings(),
        client=fake_client_for(semantic_payload()),
    )

    assert evaluation.overall_pass is True
    assert build_failure_packet(0, evaluation) is None


def test_malformed_gate_set_gets_one_format_retry() -> None:
    malformed = semantic_payload()
    malformed["gates"] = malformed["gates"][:-1] + [malformed["gates"][0]]
    evaluation = run_semantic_evaluation(
        "A complete grounded lesson.",
        LearnerProfile(),
        local_rag_facts(),
        settings=settings(),
        client=fake_client_for(malformed, semantic_payload()),
    )

    assert evaluation.overall_pass is True


def test_gate_validation_rejects_missing_or_duplicate_gates() -> None:
    malformed = semantic_payload()
    malformed["gates"] = malformed["gates"][:-1]

    with pytest.raises(ValueError, match="at least 8 items"):
        validate_gate_set(malformed)


def test_provider_schema_constrains_the_eight_expected_gate_ids() -> None:
    schema = semantic_evaluation_schema()
    gate_schema = schema["properties"]["gates"]["items"]

    assert gate_schema["properties"]["gate_id"]["enum"] == list(GATE_NAMES)
