"""Explicit LangGraph self-correction loop with auditable attempt artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from config import ensure_run_directory, get_settings
from evaluation import calculate_diagnostics, build_failure_packet, run_semantic_evaluation, run_static_checks
from lesson import (
    generate_lesson,
    inject_demo_fault,
    plan_lesson,
    revise_lesson,
    save_lesson_artifact,
)
from llm import LLMConfigurationError, LLMRequestError
from memory import (
    GuardrailDistiller,
    MemoryStore,
    distill_guardrail,
    update_memory_from_attempts,
)
from models import (
    AttemptRecord,
    CanonicalFact,
    FailurePacket,
    LearnerProfile,
    LessonPlan,
    SemanticEvaluation,
    StaticEvaluation,
    WorkflowEvent,
)
from prompts import build_generation_messages, build_revision_messages
from research import ResearchError, ResearchResult, run_research


FinalStatus = Literal["READY_TO_SHIP", "NEEDS_HUMAN_REVIEW", "RESEARCH_FAILED"]
DemoFault = Literal[
    "none", "rag_factual_error", "overly_technical_language", "remove_example_section"
]


class WorkflowData(TypedDict, total=False):
    topic: str
    learner_profile: LearnerProfile
    canonical_facts: list[CanonicalFact]
    learned_guardrails: list[str]
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

    plan: Callable[[str, LearnerProfile, list[CanonicalFact], list[str]], LessonPlan]
    generate: Callable[[str, LearnerProfile, LessonPlan, list[CanonicalFact], list[str]], str]
    revise: Callable[
        [
            str,
            LearnerProfile,
            str,
            list[CanonicalFact],
            FailurePacket | None,
            list[str],
            list[str],
        ],
        str,
    ]
    inject_fault: Callable[[str, str], str]
    static_check: Callable[[str, str, int, int], StaticEvaluation]
    semantic_check: Callable[[str, LearnerProfile, list[CanonicalFact]], SemanticEvaluation]


ResearchRunner = Callable[..., ResearchResult]
WorkflowEventSink = Callable[[dict[str, Any]], None]


class RunEventRecorder:
    """Persist progress before notifying an optional UI listener."""

    def __init__(self, run_id: str, sink: WorkflowEventSink | None = None) -> None:
        self._path = ensure_run_directory(run_id) / "events.json"
        self._sink = sink
        self._events: list[dict[str, Any]] = []
        _write_json(self._path, self._events)

    def emit(
        self,
        *,
        stage: str,
        status: Literal["started", "completed", "failed", "retry", "warning"],
        title: str,
        detail: str = "",
        attempt: int | None = None,
    ) -> None:
        event = WorkflowEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            status=status,
            title=title,
            detail=detail,
            attempt=attempt,
        ).model_dump(mode="json")
        self._events.append(event)
        _write_json(self._path, self._events)
        if self._sink is not None:
            self._sink(event)


def default_dependencies() -> WorkflowDependencies:
    """Create real local dependencies using the configured Together client helpers."""
    settings = get_settings()
    return WorkflowDependencies(
        plan=lambda topic, learner, facts, guardrails: plan_lesson(
            topic, learner, facts, guardrails, settings=settings
        ),
        generate=lambda topic, learner, lesson_plan, facts, guardrails: generate_lesson(
            topic, learner, lesson_plan, facts, guardrails, settings=settings
        ),
        revise=lambda topic, learner, lesson, facts, packet, static_failures, guardrails: revise_lesson(
            topic,
            learner,
            lesson,
            facts,
            packet,
            static_failures,
            guardrails,
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
    def serialise(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [serialise(item) for item in value]
        if isinstance(value, dict):
            return {key: serialise(item) for key, item in value.items()}
        return value

    path.write_text(json.dumps(serialise(payload), indent=2), encoding="utf-8")


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


def build_workflow(
    dependencies: WorkflowDependencies, event_recorder: RunEventRecorder | None = None
) -> Any:
    """Build the bounded LangGraph graph; every attempt follows the same evaluators."""

    graph = StateGraph(WorkflowData)

    def plan_node(state: WorkflowData) -> dict[str, Any]:
        lesson_plan = dependencies.plan(
            state["topic"],
            state["learner_profile"],
            state["canonical_facts"],
            state.get("learned_guardrails", []),
        )
        if event_recorder is not None:
            event_recorder.emit(
                stage="lesson_planning",
                status="completed",
                title="Lesson plan created",
                detail=f"{len(lesson_plan.sections)} beginner lesson sections planned",
            )
        return {"lesson_plan": lesson_plan}

    def generate_node(state: WorkflowData) -> dict[str, Any]:
        attempt = state["attempt_number"]
        if event_recorder is not None:
            event_recorder.emit(
                stage="generation",
                status="started",
                title=f"Generating attempt {attempt + 1}",
                attempt=attempt,
            )
        messages = build_generation_messages(
            state["topic"],
            state["learner_profile"],
            state["lesson_plan"],
            state["canonical_facts"],
            state.get("learned_guardrails", []),
        )
        prompt_path = _save_prompt_snapshot(
            state["run_id"], state["attempt_number"], "Initial generation prompt", messages
        )
        lesson = dependencies.generate(
            state["topic"],
            state["learner_profile"],
            state["lesson_plan"],
            state["canonical_facts"],
            state.get("learned_guardrails", []),
        )
        return {
            "current_lesson": lesson,
            "prompt_kind": "initial",
            "prompt_snapshot_path": prompt_path,
        }

    def inject_fault_node(state: WorkflowData) -> dict[str, Any]:
        lesson = dependencies.inject_fault(state["current_lesson"], state["demo_fault"])
        if event_recorder is not None and state["demo_fault"] != "none":
            event_recorder.emit(
                stage="demo_fault",
                status="warning",
                title="Demo fault injected",
                detail="Applied after generation; the evaluator is not told the fault label.",
                attempt=state["attempt_number"],
            )
        # The saved early draft, static checks, semantic evaluation, and UI all use this one artifact.
        save_lesson_artifact(lesson, state["run_id"], attempt_number=state["attempt_number"])
        if event_recorder is not None:
            event_recorder.emit(
                stage="generation",
                status="completed",
                title=f"Attempt {state['attempt_number'] + 1} generated",
                detail=f"{calculate_diagnostics(lesson)['word_count']} words",
                attempt=state["attempt_number"],
            )
        return {
            "current_lesson": lesson
        }

    def static_node(state: WorkflowData) -> dict[str, Any]:
        evaluation = dependencies.static_check(
            state["current_lesson"],
            state["topic"],
            state["attempt_number"],
            state["max_retries"],
        )
        if event_recorder is not None:
            event_recorder.emit(
                stage="static_evaluation",
                status="completed" if evaluation.passed else "failed",
                title=f"Static checks {'completed' if evaluation.passed else 'found issues'}",
                detail=(
                    f"{evaluation.word_count} words; {evaluation.learner_question_count} learner questions"
                    if evaluation.passed
                    else "; ".join(evaluation.failures)
                ),
                attempt=state["attempt_number"],
            )
        return {"static_evaluation": evaluation}

    def semantic_node(state: WorkflowData) -> dict[str, Any]:
        evaluation = dependencies.semantic_check(
            state["current_lesson"],
            state["learner_profile"],
            state["canonical_facts"],
        )
        if event_recorder is not None:
            passed_gates = sum(gate.passed for gate in evaluation.gates)
            event_recorder.emit(
                stage="semantic_evaluation",
                status="completed" if evaluation.overall_pass else "failed",
                title="Semantic evaluation completed",
                detail=f"{passed_gates}/8 quality gates passed",
                attempt=state["attempt_number"],
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
            if event_recorder is not None:
                event_recorder.emit(
                    stage="quality_decision",
                    status="completed",
                    title=f"Attempt {state['attempt_number'] + 1} passed all hard gates",
                    detail="Static checks and all 8 semantic gates passed.",
                    attempt=state["attempt_number"],
                )
            return {
                "final_status": "READY_TO_SHIP",
                "final_lesson": state["current_lesson"],
            }
        if state["attempt_number"] >= state["max_retries"]:
            if event_recorder is not None:
                event_recorder.emit(
                    stage="quality_decision",
                    status="failed",
                    title="Revision budget exhausted",
                    detail="The best lesson is available for human review.",
                    attempt=state["attempt_number"],
                )
            return {"final_status": "NEEDS_HUMAN_REVIEW"}
        if event_recorder is not None:
            failed_gates = [
                gate.gate_id for gate in state["semantic_evaluation"].gates if not gate.passed
            ]
            event_recorder.emit(
                stage="quality_decision",
                status="failed",
                title=f"Attempt {state['attempt_number'] + 1} rejected",
                detail=(
                    f"Failed gates: {', '.join(failed_gates)}"
                    if failed_gates
                    else "Static checks require a targeted revision."
                ),
                attempt=state["attempt_number"],
            )
        return {}

    def route_after_decision(state: WorkflowData) -> str:
        return "finalize" if state.get("final_status") else "revise"

    def revise_node(state: WorkflowData) -> dict[str, Any]:
        next_attempt = state["attempt_number"] + 1
        if event_recorder is not None:
            event_recorder.emit(
                stage="revision",
                status="retry",
                title="Targeted revision requested",
                detail="Evaluator evidence and deterministic failures are sent to the revision prompt.",
                attempt=next_attempt,
            )
        messages = build_revision_messages(
            state["topic"],
            state["learner_profile"],
            state["current_lesson"],
            state["canonical_facts"],
            state["failure_packet"],
            state["static_evaluation"].failures,
            state.get("learned_guardrails", []),
        )
        prompt_path = _save_prompt_snapshot(
            state["run_id"], next_attempt, "Revision prompt", messages
        )
        lesson = dependencies.revise(
            state["topic"],
            state["learner_profile"],
            state["current_lesson"],
            state["canonical_facts"],
            state["failure_packet"],
            state["static_evaluation"].failures,
            state.get("learned_guardrails", []),
        )
        # Save the exact canonical revision string that the downstream evaluators receive.
        save_lesson_artifact(lesson, state["run_id"], attempt_number=next_attempt)
        if event_recorder is not None:
            event_recorder.emit(
                stage="generation",
                status="completed",
                title=f"Attempt {next_attempt + 1} generated",
                detail=f"{calculate_diagnostics(lesson)['word_count']} words",
                attempt=next_attempt,
            )
        return {
            "current_lesson": lesson,
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
        if event_recorder is not None:
            event_recorder.emit(
                stage="workflow",
                status="completed" if state["final_status"] == "READY_TO_SHIP" else "failed",
                title=(
                    "READY TO SHIP"
                    if state["final_status"] == "READY_TO_SHIP"
                    else "NEEDS HUMAN REVIEW"
                ),
                detail="Workflow complete.",
            )
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
    learned_guardrails: list[str] | None = None,
    event_recorder: RunEventRecorder | None = None,
) -> WorkflowData:
    """Run at most three complete lesson attempts and return the final graph state."""
    if not 0 <= max_retries <= 2:
        raise ValueError("max_retries must be between 0 and 2")
    if demo_fault == "rag_factual_error" and "rag" not in topic.lower() and "retrieval-augmented generation" not in topic.lower():
        raise ValueError("The RAG factual error demo fault is available only for RAG-like topics.")
    ensure_run_directory(run_id)
    workflow = build_workflow(dependencies or default_dependencies(), event_recorder)
    return workflow.invoke(
        {
            "topic": topic,
            "learner_profile": learner_profile or LearnerProfile(),
            "canonical_facts": canonical_facts,
            "learned_guardrails": learned_guardrails or [],
            "run_id": run_id,
            "max_retries": max_retries,
            "demo_fault": demo_fault,
            "attempt_number": 0,
            "attempt_history": [],
            "rejection_log": [],
        }
    )


def _save_research_failure(run_id: str, topic: str, error: Exception) -> WorkflowData:
    """Persist a terminal, inspectable outcome instead of generating without grounding."""
    run_directory = ensure_run_directory(run_id)
    error_message = str(error)
    rejection_log = [{"stage": "research", "error": error_message}]
    _write_json(run_directory / "rejection_log.json", rejection_log)
    _write_json(
        run_directory / "run_summary.json",
        {
            "run_id": run_id,
            "topic": topic,
            "final_status": "RESEARCH_FAILED",
            "attempt_count": 0,
            "attempts": [],
            "error": error_message,
        },
    )
    return {
        "topic": topic,
        "run_id": run_id,
        "final_status": "RESEARCH_FAILED",
        "attempt_history": [],
        "rejection_log": rejection_log,
        "error": error_message,
    }


def _read_artifact_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _completed_attempts(run_directory: Path) -> list[AttemptRecord]:
    """Rebuild completed attempt records if a provider request fails mid-graph."""
    records: list[AttemptRecord] = []
    for static_path in sorted(run_directory.glob("static_evaluation_*.json")):
        attempt_number = int(static_path.stem.removeprefix("static_evaluation_"))
        semantic_path = run_directory / f"evaluation_{attempt_number}.json"
        if not semantic_path.is_file():
            continue
        try:
            failure_path = run_directory / f"failure_packet_{attempt_number}.json"
            records.append(
                AttemptRecord(
                    attempt_number=attempt_number,
                    lesson_path=str(run_directory / f"attempt_{attempt_number}.md"),
                    prompt_kind="initial" if attempt_number == 0 else "revision",
                    prompt_snapshot_path=str(run_directory / f"prompt_{attempt_number}.md"),
                    revision_feedback=(
                        FailurePacket.model_validate(_read_artifact_json(failure_path, {}))
                        if failure_path.is_file()
                        else None
                    ),
                    static_evaluation=StaticEvaluation.model_validate(
                        _read_artifact_json(static_path, {})
                    ),
                    semantic_evaluation=SemanticEvaluation.model_validate(
                        _read_artifact_json(semantic_path, {})
                    ),
                )
            )
        except (ValueError, TypeError):
            continue
    return records


def _save_workflow_failure(run_id: str, topic: str, error: LLMRequestError) -> WorkflowData:
    """Make a mid-workflow Together failure reviewable instead of silently losing progress."""
    run_directory = ensure_run_directory(run_id)
    attempts = _completed_attempts(run_directory)
    error_payload = {
        "stage": "lesson_generation_or_evaluation",
        "error_type": type(error).__name__,
        "message": str(error),
        "last_completed_attempt": attempts[-1].attempt_number if attempts else None,
    }
    rejection_log = [
        {
            "attempt": record.attempt_number,
            "static_failures": record.static_evaluation.failures if record.static_evaluation else [],
            "failed_gates": [
                gate.model_dump(mode="json")
                for gate in (record.semantic_evaluation.gates if record.semantic_evaluation else [])
                if not gate.passed
            ],
        }
        for record in attempts
        if not (
            record.static_evaluation
            and record.static_evaluation.passed
            and record.semantic_evaluation
            and record.semantic_evaluation.overall_pass
        )
    ]
    rejection_log.append({"stage": "provider", "error": error_payload})
    _write_json(run_directory / "workflow_error.json", error_payload)
    _write_json(run_directory / "rejection_log.json", rejection_log)
    _write_json(
        run_directory / "run_summary.json",
        {
            "run_id": run_id,
            "topic": topic,
            "final_status": "NEEDS_HUMAN_REVIEW",
            "attempt_count": len(attempts),
            "attempts": [record.model_dump(mode="json") for record in attempts],
            "error": error_payload,
        },
    )
    return {
        "topic": topic,
        "run_id": run_id,
        "final_status": "NEEDS_HUMAN_REVIEW",
        "attempt_history": attempts,
        "rejection_log": rejection_log,
        "error": str(error),
    }


def run_dynamic_workflow(
    topic: str,
    *,
    learner_profile: LearnerProfile | None = None,
    run_id: str,
    max_retries: int = 2,
    demo_fault: DemoFault = "none",
    dependencies: WorkflowDependencies | None = None,
    research_runner: ResearchRunner = run_research,
    memory_store: MemoryStore | None = None,
    guardrail_distiller: GuardrailDistiller | None = None,
    event_sink: WorkflowEventSink | None = None,
) -> WorkflowData:
    """Research a topic and run the full lesson-quality loop using that run's facts.

    The research and lesson artifacts deliberately share one run directory, so an
    interviewer can trace the exact source evidence behind every generated attempt.
    """
    learner = learner_profile or LearnerProfile()
    event_recorder = RunEventRecorder(run_id, event_sink)
    event_recorder.emit(
        stage="workflow",
        status="started",
        title="Workflow started",
        detail="Preparing research and grounded lesson generation.",
    )
    settings = get_settings()
    store = memory_store or MemoryStore()
    loaded_guardrails = store.active_guardrails(settings.max_active_guardrails)
    learned_guardrails = [guardrail.rule for guardrail in loaded_guardrails]
    print(f"Loaded {len(learned_guardrails)} learned guardrails from memory.")
    run_directory = ensure_run_directory(run_id)
    _write_json(run_directory / "loaded_guardrails.json", loaded_guardrails)
    event_recorder.emit(
        stage="memory",
        status="completed",
        title="Cross-run memory loaded",
        detail=f"{len(loaded_guardrails)} learned guardrails available.",
    )
    event_recorder.emit(
        stage="research",
        status="started",
        title="Research and grounding started",
        detail="Creating a topic-specific research plan.",
    )
    try:
        research_result = research_runner(
            topic, learner=learner, run_id=run_id
        )
    except (ResearchError, LLMConfigurationError, LLMRequestError) as error:
        event_recorder.emit(
            stage="research",
            status="failed",
            title="Research failed",
            detail=str(error),
        )
        return _save_research_failure(run_id, topic, error)
    research_plan = getattr(research_result, "plan", None)
    candidates = getattr(research_result, "candidates", [])
    selected_sources = getattr(research_result, "selected_sources", [])
    event_recorder.emit(
        stage="research_planning",
        status="completed",
        title="Research plan created",
        detail=(
            f"{len(research_plan.search_queries)} search queries prepared"
            if research_plan is not None
            else "Topic-specific research plan completed."
        ),
    )
    event_recorder.emit(
        stage="source_discovery",
        status="completed",
        title="Source discovery complete",
        detail=f"{len(candidates)} candidate sources found",
    )
    event_recorder.emit(
        stage="source_curation",
        status="completed",
        title="Authoritative sources selected",
        detail=f"{len(selected_sources)} sources selected",
    )
    event_recorder.emit(
        stage="grounding",
        status="completed",
        title="Grounded facts built",
        detail=f"{len(research_result.canonical_facts)} canonical facts extracted",
    )
    try:
        state = run_workflow(
            topic,
            research_result.canonical_facts,
            learner_profile=learner,
            run_id=run_id,
            max_retries=max_retries,
            demo_fault=demo_fault,
            dependencies=dependencies,
            learned_guardrails=learned_guardrails,
            event_recorder=event_recorder,
        )
    except LLMRequestError as error:
        event_recorder.emit(
            stage="workflow",
            status="failed",
            title="Provider request failed",
            detail=str(error),
        )
        state = _save_workflow_failure(run_id, topic, error)
    if demo_fault == "none":
        update = update_memory_from_attempts(
            store,
            run_id,
            state.get("attempt_history", []),
            threshold=settings.guardrail_failure_threshold,
            distiller=guardrail_distiller or distill_guardrail,
        )
        _write_json(
            run_directory / "memory_update.json",
            {
                "recorded_gate_ids": update.recorded_gate_ids,
                "promoted_guardrails": update.promoted_guardrails,
                "distillation_errors": update.distillation_errors,
            },
        )
        if update.promoted_guardrails:
            print(f"Promoted {len(update.promoted_guardrails)} learned guardrail(s).")
    else:
        _write_json(
            run_directory / "memory_update.json",
            {"skipped": "Demo-fault runs do not update cross-run learning memory."},
        )
    state["learned_guardrails"] = learned_guardrails
    event_recorder.emit(
        stage="memory",
        status="completed",
        title="Cross-run memory updated",
        detail="Run failures were checked for recurring patterns.",
    )
    return state
