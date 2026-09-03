from __future__ import annotations

import json
from pathlib import Path

from evaluation import run_static_checks
from lesson import inject_demo_fault
from models import GateResult, LessonPlan, SemanticEvaluation
from tests.lesson_fixtures import TOPIC, good_lesson, short_lesson
from tests.rag_facts_fixture import local_rag_facts
from workflow import WorkflowDependencies, run_workflow


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


def semantic_result(*failed_gate_ids: str) -> SemanticEvaluation:
    failed = set(failed_gate_ids)
    return SemanticEvaluation(
        gates=[
            GateResult(
                gate_id=gate_id,
                name=name,
                passed=gate_id not in failed,
                evidence=f"Evidence for {gate_id}",
                reason="Requirement not met." if gate_id in failed else "Requirement met.",
                required_fix="Fix this requirement."
                if gate_id in failed
                else "No change needed.",
            )
            for gate_id, name in GATE_NAMES.items()
        ]
    )


def test_factual_demo_fault_is_repaired_and_audited(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    evaluated_lessons: list[str] = []

    def semantic_check(lesson, learner, facts):
        evaluated_lessons.append(lesson)
        if "retrains the language model's weights" in lesson:
            return semantic_result("R1")
        return semantic_result()

    dependencies = WorkflowDependencies(
        plan=lambda topic, learner, facts: LessonPlan(title=topic, sections=["Problem"]),
        generate=lambda topic, learner, plan, facts: good_lesson(),
        revise=lambda topic, learner, lesson, facts, packet, static_failures: good_lesson(),
        inject_fault=inject_demo_fault,
        static_check=lambda lesson, topic, attempt, max_retries: run_static_checks(
            lesson, topic, attempt_number=attempt, max_retries=max_retries
        ),
        semantic_check=semantic_check,
    )

    state = run_workflow(
        TOPIC,
        local_rag_facts(),
        run_id="factual_repair",
        demo_fault="rag_factual_error",
        dependencies=dependencies,
    )

    run_directory = tmp_path / "runs" / "factual_repair"
    assert state["final_status"] == "READY_TO_SHIP"
    assert len(state["attempt_history"]) == 2
    assert state["attempt_history"][0].semantic_evaluation.overall_pass is False
    assert state["attempt_history"][1].semantic_evaluation.overall_pass is True
    assert "retrains the language model's weights" in evaluated_lessons[0]
    assert "retrains the language model's weights" not in evaluated_lessons[1]
    assert (run_directory / "prompt_0.md").is_file()
    assert (run_directory / "prompt_1.md").is_file()
    assert (run_directory / "failure_packet_0.json").is_file()
    assert (run_directory / "final_lesson.md").is_file()
    summary = json.loads((run_directory / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["attempt_count"] == 2


def test_static_failure_routes_to_revision_even_when_semantic_gates_pass(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    static_feedback: list[list[str]] = []
    calls = {"generate": 0}

    def generate(topic, learner, plan, facts):
        calls["generate"] += 1
        return short_lesson()

    def revise(topic, learner, lesson, facts, packet, static_failures):
        static_feedback.append(static_failures)
        return good_lesson()

    dependencies = WorkflowDependencies(
        plan=lambda topic, learner, facts: LessonPlan(title=topic, sections=["Problem"]),
        generate=generate,
        revise=revise,
        inject_fault=lambda lesson, fault: lesson,
        static_check=lambda lesson, topic, attempt, max_retries: run_static_checks(
            lesson, topic, attempt_number=attempt, max_retries=max_retries
        ),
        semantic_check=lambda lesson, learner, facts: semantic_result(),
    )

    state = run_workflow(
        TOPIC, local_rag_facts(), run_id="static_repair", dependencies=dependencies
    )

    assert state["final_status"] == "READY_TO_SHIP"
    assert len(state["attempt_history"]) == 2
    assert static_feedback and any("700-2200" in item for item in static_feedback[0])


def test_retries_exhaust_after_three_total_attempts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    revision_count = 0

    def revise(topic, learner, lesson, facts, packet, static_failures):
        nonlocal revision_count
        revision_count += 1
        return good_lesson()

    dependencies = WorkflowDependencies(
        plan=lambda topic, learner, facts: LessonPlan(title=topic, sections=["Problem"]),
        generate=lambda topic, learner, plan, facts: good_lesson(),
        revise=revise,
        inject_fault=lambda lesson, fault: lesson,
        static_check=lambda lesson, topic, attempt, max_retries: run_static_checks(
            lesson, topic, attempt_number=attempt, max_retries=max_retries
        ),
        semantic_check=lambda lesson, learner, facts: semantic_result("R3"),
    )

    state = run_workflow(
        TOPIC,
        local_rag_facts(),
        run_id="retries_exhausted",
        max_retries=2,
        dependencies=dependencies,
    )

    run_directory = Path(tmp_path / "runs" / "retries_exhausted")
    assert state["final_status"] == "NEEDS_HUMAN_REVIEW"
    assert len(state["attempt_history"]) == 3
    assert revision_count == 2
    assert not (run_directory / "final_lesson.md").exists()
    assert json.loads((run_directory / "rejection_log.json").read_text(encoding="utf-8"))
