"""Lesson planning, generation, and local artifact persistence."""

from __future__ import annotations

from pathlib import Path

from config import Settings, ensure_run_directory, get_settings
from llm import LLMRequestError, call_json_model, call_text_model
from models import CanonicalFact, FailurePacket, LearnerProfile, LessonPlan
from prompts import build_generation_messages, build_lesson_plan_messages
from prompts import build_revision_messages


def plan_lesson(
    topic: str,
    learner: LearnerProfile,
    canonical_facts: list[CanonicalFact],
    learned_guardrails: list[str] | None = None,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> LessonPlan:
    """Produce a structured plan grounded in the provided canonical facts."""
    settings = settings or get_settings()
    try:
        response = call_json_model(
            build_lesson_plan_messages(topic, learner, canonical_facts, learned_guardrails),
            model=settings.fast_model,
            fallback_model=settings.fast_model_fallback,
            max_tokens=settings.fast_model_max_tokens,
            json_schema=LessonPlan.model_json_schema(),
            schema_name="lesson_plan",
            client=client,  # type: ignore[arg-type]
            settings=settings,
        )
        return LessonPlan.model_validate(response)
    except (LLMRequestError, ValueError) as error:
        raise LLMRequestError("Unable to create a valid lesson plan.") from error


def generate_lesson(
    topic: str,
    learner: LearnerProfile,
    lesson_plan: LessonPlan,
    canonical_facts: list[CanonicalFact],
    learned_guardrails: list[str] | None = None,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> str:
    """Generate a complete first-attempt lesson from an auditable fact contract."""
    settings = settings or get_settings()
    return call_text_model(
        build_generation_messages(
            topic, learner, lesson_plan, canonical_facts, learned_guardrails
        ),
        model=settings.generator_model,
        fallback_model=settings.generator_model_fallback,
        max_tokens=settings.generator_model_max_tokens,
        client=client,  # type: ignore[arg-type]
        settings=settings,
    )


def revise_lesson(
    topic: str,
    learner: LearnerProfile,
    previous_lesson: str,
    canonical_facts: list[CanonicalFact],
    failure_packet: FailurePacket | None,
    static_failures: list[str],
    learned_guardrails: list[str] | None = None,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> str:
    """Return a complete revised lesson using evaluator feedback, never a patch description."""
    settings = settings or get_settings()
    return call_text_model(
        build_revision_messages(
            topic,
            learner,
            previous_lesson,
            canonical_facts,
            failure_packet,
            static_failures,
            learned_guardrails,
        ),
        model=settings.generator_model,
        fallback_model=settings.generator_model_fallback,
        max_tokens=settings.generator_model_max_tokens,
        client=client,  # type: ignore[arg-type]
        settings=settings,
    )


def inject_demo_fault(lesson: str, fault: str) -> str:
    """Apply a traceable demo-only defect to the first generated attempt."""
    if fault == "none":
        return lesson
    if fault == "rag_factual_error":
        false_claim = (
            "\n\nFor every user question, RAG retrains the language model's weights before "
            "answering, so the model learns the new information permanently.\n"
        )
        marker = "## Important terms"
        return lesson.replace(marker, false_claim + "\n" + marker, 1)
    if fault == "overly_technical_language":
        return lesson + (
            "\n\nThe architecture performs approximate nearest-neighbor retrieval over latent "
            "embedding manifolds before transformer autoregression.\n"
        )
    if fault == "remove_example_section":
        import re

        return re.sub(
            r"^## Step-by-step example\s*$.*?(?=^## |\Z)",
            "",
            lesson,
            flags=re.MULTILINE | re.DOTALL,
        )
    raise ValueError(f"Unsupported demo fault: {fault}")


def save_lesson_artifact(lesson: str, run_id: str, *, attempt_number: int = 0) -> Path:
    """Save a generated lesson in its run directory for inspection and later evaluation."""
    if attempt_number < 0:
        raise ValueError("attempt_number must be zero or greater")
    artifact_path = ensure_run_directory(run_id) / f"attempt_{attempt_number}.md"
    artifact_path.write_text(lesson, encoding="utf-8")
    return artifact_path
