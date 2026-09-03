from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from evaluation import run_static_checks
from memory import MemoryStore, update_memory_from_attempts
from models import AttemptRecord, GateResult, LearnerProfile, LessonPlan, SemanticEvaluation
from prompts import build_generation_messages
from tests.lesson_fixtures import TOPIC, good_lesson
from tests.rag_facts_fixture import local_rag_facts
from workflow import WorkflowDependencies, run_dynamic_workflow


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


def failed_attempt(gate_id: str) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=0,
        lesson_path="attempt_0.md",
        semantic_evaluation=SemanticEvaluation(
            gates=[
                GateResult(
                    gate_id=gate,
                    name=name,
                    passed=gate != gate_id,
                    evidence=f"Evidence for {gate}",
                    reason="Repeated beginner-language issue." if gate == gate_id else "Pass.",
                    required_fix="Use a familiar explanation before technical vocabulary."
                    if gate == gate_id
                    else "None.",
                )
                for gate, name in GATE_NAMES.items()
            ]
        ),
    )


def test_same_run_failures_count_once_and_do_not_promote(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    distiller_calls: list[str] = []
    distiller = lambda gate_id, examples: distiller_calls.append(gate_id) or "Guardrail"

    update_memory_from_attempts(
        store, "run_a", [failed_attempt("R3"), failed_attempt("R3")], threshold=2, distiller=distiller
    )
    update_memory_from_attempts(
        store, "run_a", [failed_attempt("R3")], threshold=2, distiller=distiller
    )

    assert store.failure_count("R3") == 1
    assert distiller_calls == []
    assert store.active_guardrails() == []


def test_two_distinct_run_failures_promote_and_persist_guardrail(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    distiller = lambda gate_id, examples: (
        "Begin with a familiar problem and define the basic idea before technical terms."
    )

    first = update_memory_from_attempts(
        store, "run_a", [failed_attempt("R3")], threshold=2, distiller=distiller
    )
    second = update_memory_from_attempts(
        store, "run_b", [failed_attempt("R3")], threshold=2, distiller=distiller
    )

    restarted_store = MemoryStore(database_path)
    guardrails = restarted_store.active_guardrails()
    assert first.promoted_guardrails == []
    assert len(second.promoted_guardrails) == 1
    assert guardrails[0].gate_id == "R3"
    assert guardrails[0].source_run_count == 2
    assert "familiar problem" in guardrails[0].rule


def test_active_guardrails_are_capped_and_injected_into_initial_prompt(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    for index, gate_id in enumerate(["R1", "R2", "R3", "R4", "R5", "R6"], start=1):
        store.save_guardrail(gate_id, f"Guardrail {index}", source_run_count=2)

    guardrails = store.active_guardrails(limit=5)
    messages = build_generation_messages(
        "Introduction to RAG",
        learner=LearnerProfile(),
        lesson_plan=LessonPlan(title="Introduction to RAG", sections=["Problem"]),
        canonical_facts=local_rag_facts(),
        learned_guardrails=[guardrail.rule for guardrail in guardrails],
    )

    assert len(guardrails) == 5
    assert "Active learned guardrails" in messages[1]["content"]
    assert guardrails[0].rule in messages[1]["content"]


def test_future_dynamic_run_loads_promoted_guardrail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    store = MemoryStore(tmp_path / "memory.db")
    received_guardrails: list[list[str]] = []

    def research_runner(topic, *, learner, run_id):
        return SimpleNamespace(canonical_facts=local_rag_facts())

    dependencies = WorkflowDependencies(
        plan=lambda topic, learner, facts, guardrails: (
            received_guardrails.append(guardrails)
            or LessonPlan(title=topic, sections=["Problem"])
        ),
        generate=lambda topic, learner, plan, facts, guardrails: good_lesson(),
        revise=lambda topic, learner, lesson, facts, packet, static_failures, guardrails: good_lesson(),
        inject_fault=lambda lesson, fault: lesson,
        static_check=lambda lesson, topic, attempt, max_retries: run_static_checks(
            lesson, topic, attempt_number=attempt, max_retries=max_retries
        ),
        semantic_check=lambda lesson, learner, facts: failed_attempt("R3").semantic_evaluation,
    )
    distiller = lambda gate_id, examples: "Start with a familiar problem before technical terms."

    for run_id in ["memory_run_one", "memory_run_two", "memory_run_three"]:
        run_dynamic_workflow(
            TOPIC,
            run_id=run_id,
            max_retries=0,
            dependencies=dependencies,
            research_runner=research_runner,
            memory_store=store,
            guardrail_distiller=distiller,
        )

    assert received_guardrails[0] == []
    assert received_guardrails[1] == []
    assert received_guardrails[2] == [
        "Start with a familiar problem before technical terms."
    ]
