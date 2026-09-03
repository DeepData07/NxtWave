"""Explicit LangGraph self-correction loop with auditable attempt artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from config import ensure_run_directory, get_settings
from evaluation import build_failure_packet, run_semantic_evaluation, run_static_checks
from lesson import (
    generate_lesson,
    inject_demo_fault,
    plan_lesson,
    revise_lesson,
    save_lesson_artifact,
)
from models import (
    AttemptRecord,
    CanonicalFact,
    FailurePacket,
    LearnerProfile,
    LessonPlan,
    SemanticEvaluation,
    StaticEvaluation,
)
from prompts import build_generation_messages, build_revision_messages


FinalStatus = Literal["READY_TO_SHIP", "NEEDS_HUMAN_REVIEW"]
DemoFault = Literal[
    "none", "rag_factual_error", "overly_technical_language", "remove_example_section"
]


class WorkflowData(TypedDict, total=False):
    topic: str
    learner_profile: LearnerProfile
    canonical_facts: list[CanonicalFact]
    run_id: str
    max_retries: int
    demo_fault: DemoFault
    lesson_plan: LessonPlan
    current_lesson: str
    attempt_number: int
    static_evaluation: StaticEvaluation
    semantic_evaluation: SemanticEvaluation
    failure_packet: FailurePacket | None
    prompt_kind: Literal["initial", "revision"]
    prompt_snapshot_path: str
    attempt_history: list[AttemptRecord]
    rejection_log: list[dict[str, Any]]
    final_status: FinalStatus
    final_lesson: str
    error: str


@dataclass(frozen=True)
class WorkflowDependencies:
    """Injectable operations keep workflow-routing tests free from paid API calls."""

    plan: Callable[[str, LearnerProfile, list[CanonicalFact]], LessonPlan]
    generate: Callable[[str, LearnerProfile, LessonPlan, list[CanonicalFact]], str]
    revise: Callable[
        [str, LearnerProfile, str, list[CanonicalFact], FailurePacket | None, list[str]], str
    ]
    inject_fault: Callable[[str, str], str]
    static_check: Callable[[str, str, int, int], StaticEvaluation]
    semantic_check: Callable[[str, LearnerProfile, list[CanonicalFact]], SemanticEvaluation]


def default_dependencies() -> WorkflowDependencies:
    """Create real local dependencies using the configured Together client helpers."""
    settings = get_settings()
    return WorkflowDependencies(
        plan=lambda topic, learner, facts: plan_lesson(
            topic, learner, facts, settings=settings
        ),
        generate=lambda topic, learner, lesson_plan, facts: generate_lesson(
            topic, learner, lesson_plan, facts, settings=settings
        ),
        revise=lambda topic, learner, lesson, facts, packet, static_failures: revise_lesson(
            topic,
            learner,
            lesson,
            facts,
            packet,
            static_failures,
            settings=settings,
        ),
        inject_fault=inject_demo_fault,
        static_check=lambda lesson, topic, attempt, max_retries: run_static_checks(
            lesson, topic, attempt_number=attempt, max_retries=max_retries
        ),
        semantic_check=lambda lesson, learner, facts: run_semantic_evaluation(
            lesson, learner, facts, settings=settings
        ),
    )


def _write_json(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _render_prompt(title: str, messages: list[dict[str, str]]) -> str:
    sections = [f"# {title}"]
    for message in messages:
        sections.append(f"## {message['role'].title()}\n\n{message['content']}")
    return "\n\n".join(sections) + "\n"


def _save_prompt_snapshot(
    run_id: str, attempt_number: int, title: str, messages: list[dict[str, str]]
) -> str:
    path = ensure_run_directory(run_id) / f"prompt_{attempt_number}.md"
    path.write_text(_render_prompt(title, messages), encoding="utf-8")
    return str(path)


def build_workflow(dependencies: WorkflowDependencies) -> Any:
    """Build the bounded LangGraph graph; every attempt follows the same evaluators."""

    graph = StateGraph(WorkflowData)

    def plan_node(state: WorkflowData) -> dict[str, Any]:
        return {
            "lesson_plan": dependencies.plan(
                state["topic"], state["learner_profile"], state["canonical_facts"]
            )
        }

    def generate_node(state: WorkflowData) -> dict[str, Any]:
        messages = build_generation_messages(
            state["topic"],
            state["learner_profile"],
            state["lesson_plan"],
            state["canonical_facts"],
        )
        prompt_path = _save_prompt_snapshot(
            state["run_id"], state["attempt_number"], "Initial generation prompt", messages
        )
        return {
            "current_lesson": dependencies.generate(
                state["topic"],
                state["learner_profile"],
                state["lesson_plan"],
                state["canonical_facts"],
            ),
            "prompt_kind": "initial",
            "prompt_snapshot_path": prompt_path,
        }

    def inject_fault_node(state: WorkflowData) -> dict[str, Any]:
        return {
            "current_lesson": dependencies.inject_fault(
                state["current_lesson"], state["demo_fault"]
            )
        }

    def static_node(state: WorkflowData) -> dict[str, Any]:
        return {
            "static_evaluation": dependencies.static_check(
                state["current_lesson"],
                state["topic"],
                state["attempt_number"],
                state["max_retries"],
            )
        }

    def semantic_node(state: WorkflowData) -> dict[str, Any]:
        evaluation = dependencies.semantic_check(
            state["current_lesson"],
            state["learner_profile"],
            state["canonical_facts"],
        )
        return {
            "semantic_evaluation": evaluation,
            "failure_packet": build_failure_packet(state["attempt_number"], evaluation),
        }

    def persist_attempt_node(state: WorkflowData) -> dict[str, Any]:
        run_directory = ensure_run_directory(state["run_id"])
        attempt = state["attempt_number"]
        save_lesson_artifact(state["current_lesson"], state["run_id"], attempt_number=attempt)
        _write_json(run_directory / f"static_evaluation_{attempt}.json", state["static_evaluation"])
        _write_json(run_directory / f"evaluation_{attempt}.json", state["semantic_evaluation"])
        if state["failure_packet"] is not None:
            _write_json(run_directory / f"failure_packet_{attempt}.json", state["failure_packet"])

        record = AttemptRecord(
            attempt_number=attempt,
            lesson_path=str(run_directory / f"attempt_{attempt}.md"),
            prompt_kind=state["prompt_kind"],
            prompt_snapshot_path=state["prompt_snapshot_path"],
            revision_feedback=state["failure_packet"],
            static_evaluation=state["static_evaluation"],
            semantic_evaluation=state["semantic_evaluation"],
        )
        rejection_log = list(state.get("rejection_log", []))
        if not (state["static_evaluation"].passed and state["semantic_evaluation"].overall_pass):
            rejection_log.append(
                {
                    "attempt": attempt,
                    "static_failures": state["static_evaluation"].failures,
                    "failed_gates": [
                        gate.model_dump(mode="json")
                        for gate in state["semantic_evaluation"].gates
                        if not gate.passed
                    ],
                }
            )
        return {
            "attempt_history": [*state.get("attempt_history", []), record],
            "rejection_log": rejection_log,
        }

    def decide_node(state: WorkflowData) -> dict[str, Any]:
        all_passed = (
            state["static_evaluation"].passed
            and state["semantic_evaluation"].overall_pass
        )
        if all_passed:
            return {
                "final_status": "READY_TO_SHIP",
                "final_lesson": state["current_lesson"],
            }
        if state["attempt_number"] >= state["max_retries"]:
            return {"final_status": "NEEDS_HUMAN_REVIEW"}
        return {}

    def route_after_decision(state: WorkflowData) -> str:
        return "finalize" if state.get("final_status") else "revise"

    def revise_node(state: WorkflowData) -> dict[str, Any]:
        next_attempt = state["attempt_number"] + 1
        messages = build_revision_messages(
            state["topic"],
            state["learner_profile"],
            state["current_lesson"],
            state["canonical_facts"],
            state["failure_packet"],
            state["static_evaluation"].failures,
        )
        prompt_path = _save_prompt_snapshot(
            state["run_id"], next_attempt, "Revision prompt", messages
        )
        return {
            "current_lesson": dependencies.revise(
                state["topic"],
                state["learner_profile"],
                state["current_lesson"],
                state["canonical_facts"],
                state["failure_packet"],
                state["static_evaluation"].failures,
            ),
            "attempt_number": next_attempt,
            "prompt_kind": "revision",
            "prompt_snapshot_path": prompt_path,
        }

    def finalize_node(state: WorkflowData) -> dict[str, Any]:
        run_directory = ensure_run_directory(state["run_id"])
        if state["final_status"] == "READY_TO_SHIP":
            (run_directory / "final_lesson.md").write_text(
                state["final_lesson"], encoding="utf-8"
            )
        _write_json(run_directory / "rejection_log.json", state.get("rejection_log", []))
        summary = {
            "run_id": state["run_id"],
            "topic": state["topic"],
            "final_status": state["final_status"],
            "attempt_count": len(state.get("attempt_history", [])),
            "attempts": [record.model_dump(mode="json") for record in state.get("attempt_history", [])],
        }
        _write_json(run_directory / "run_summary.json", summary)
        return {}

    graph.add_node("plan_lesson", plan_node)
    graph.add_node("generate_lesson", generate_node)
    graph.add_node("inject_demo_fault", inject_fault_node)
    graph.add_node("run_static_checks", static_node)
    graph.add_node("evaluate_semantically", semantic_node)
    graph.add_node("persist_attempt", persist_attempt_node)
    graph.add_node("decide_quality", decide_node)
    graph.add_node("revise_lesson", revise_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "plan_lesson")
    graph.add_edge("plan_lesson", "generate_lesson")
    graph.add_edge("generate_lesson", "inject_demo_fault")
    graph.add_edge("inject_demo_fault", "run_static_checks")
    graph.add_edge("run_static_checks", "evaluate_semantically")
    graph.add_edge("evaluate_semantically", "persist_attempt")
    graph.add_edge("persist_attempt", "decide_quality")
    graph.add_conditional_edges(
        "decide_quality",
        route_after_decision,
        {"finalize": "finalize", "revise": "revise_lesson"},
    )
    graph.add_edge("revise_lesson", "run_static_checks")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_workflow(
    topic: str,
    canonical_facts: list[CanonicalFact],
    *,
    learner_profile: LearnerProfile | None = None,
    run_id: str,
    max_retries: int = 2,
    demo_fault: DemoFault = "none",
    dependencies: WorkflowDependencies | None = None,
) -> WorkflowData:
    """Run at most three complete lesson attempts and return the final graph state."""
    if not 0 <= max_retries <= 2:
        raise ValueError("max_retries must be between 0 and 2")
    ensure_run_directory(run_id)
    workflow = build_workflow(dependencies or default_dependencies())
    return workflow.invoke(
        {
            "topic": topic,
            "learner_profile": learner_profile or LearnerProfile(),
            "canonical_facts": canonical_facts,
            "run_id": run_id,
            "max_retries": max_retries,
            "demo_fault": demo_fault,
            "attempt_number": 0,
            "attempt_history": [],
            "rejection_log": [],
        }
    )
