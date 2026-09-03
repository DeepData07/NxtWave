"""Visible prompt builders for the lesson planning and generation roles."""

from __future__ import annotations

import json

from evaluation import expected_headings
from models import CanonicalFact, LearnerProfile, LessonPlan


def _learner_context(learner: LearnerProfile) -> str:
    return json.dumps(learner.model_dump(), indent=2)


def _facts_context(canonical_facts: list[CanonicalFact]) -> str:
    return "\n".join(
        f"- {fact.fact_id} | {fact.concept}: {fact.statement}"
        for fact in canonical_facts
        if fact.status != "conflicting"
    )


def build_lesson_plan_messages(
    topic: str, learner: LearnerProfile, canonical_facts: list[CanonicalFact]
) -> list[dict[str, str]]:
    """Create a compact structured-planning prompt from the local knowledge contract."""
    return [
        {
            "role": "system",
            "content": (
                "You plan beginner lessons. Return only a JSON object with a concise "
                '"title" and a "sections" list. The list must contain the eight section '
                "names from the requested heading contract. Use a familiar problem first, "
                "then explain the idea, mechanism, example, limits, recap, and questions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic}\n\nLearner profile:\n{_learner_context(learner)}"
                f"\n\nSupported facts (use only these as factual grounding):\n"
                f"{_facts_context(canonical_facts)}"
            ),
        },
    ]


def build_generation_messages(
    topic: str,
    learner: LearnerProfile,
    lesson_plan: LessonPlan,
    canonical_facts: list[CanonicalFact],
) -> list[dict[str, str]]:
    """Create the initial-generation prompt without evaluator feedback."""
    headings = expected_headings(topic)
    heading_contract = "\n".join(
        [f"# {headings[0]}"] + [f"## {heading}" for heading in headings[1:]]
    )
    return [
        {
            "role": "system",
            "content": (
                "Write one complete standalone Markdown lesson for a true beginner. "
                "Use short, clear sentences and define technical words on first use. "
                "Use only the supplied facts for technical claims. Do not invent sources, "
                "URLs, or unsupported facts. Return the lesson only, with no preamble."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic}\n\nLearner profile:\n{_learner_context(learner)}"
                f"\n\nLesson outline:\n{json.dumps(lesson_plan.model_dump(), indent=2)}"
                f"\n\nSupported facts:\n{_facts_context(canonical_facts)}"
                "\n\nWrite 900-1400 words. Use these exact Markdown headings:\n"
                f"{heading_contract}\n\n"
                "The Step-by-step example must use a familiar situation and walk through "
                "the full process. The final section must contain at least three questions."
            ),
        },
    ]
