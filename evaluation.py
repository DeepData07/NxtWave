"""Deterministic lesson checks and readability diagnostics.

Semantic quality remains a later LLM-evaluation stage. This module deliberately
uses only normal Python for measurable constraints.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from config import Settings, get_settings
from llm import LLMRequestError, call_json_model
from models import (
    CanonicalFact,
    FailurePacket,
    LearnerProfile,
    SemanticEvaluation,
    StaticEvaluation,
)


HARD_MIN_WORDS = 700
HARD_MAX_WORDS = 2200
MAX_LONG_SENTENCE_WORDS = 30

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WORD_PATTERN = re.compile(r"\b[\w'-]+\b")
_SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+\S", re.MULTILINE)
_NUMBERED_QUESTION_PATTERN = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$", re.MULTILINE)
_FENCED_CODE_PATTERN = re.compile(r"^\s*```", re.MULTILINE)
_UNESCAPED_DOLLAR_PATTERN = re.compile(r"(?<!\\)\$")


class SemanticEvaluationError(RuntimeError):
    """Raised when a semantic evaluation cannot be obtained in the allowed format retries."""


def expected_headings(topic: str) -> list[str]:
    """Return the predictable heading contract for a lesson topic."""
    subject = re.sub(r"^what is\s+", "", topic, flags=re.IGNORECASE).rstrip("?!: ")
    concept_heading = (
        f"What does {subject} mean?"
        if re.match(r"^what is\s+", topic, flags=re.IGNORECASE)
        else f"What is {topic}"
    )
    return [
        topic,
        "Start with a simple problem",
        concept_heading,
        "Why does it matter",
        "How does it work",
        "Step-by-step example",
        "Important terms",
        "Limitations",
        "Quick recap",
        "Check your understanding",
    ]


def calculate_diagnostics(lesson: str) -> dict[str, float | int]:
    """Calculate readability indicators without treating them as quality proof."""
    body = _HEADING_PATTERN.sub("", lesson)
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_PATTERN.findall(body)
        if _WORD_PATTERN.search(sentence)
    ]
    sentence_lengths = [len(_WORD_PATTERN.findall(sentence)) for sentence in sentences]
    word_count = len(_WORD_PATTERN.findall(lesson))
    heading_count = len(_HEADING_PATTERN.findall(lesson))

    return {
        "word_count": word_count,
        "average_sentence_length": round(
            sum(sentence_lengths) / len(sentence_lengths), 2
        )
        if sentence_lengths
        else 0.0,
        "long_sentence_count": sum(
            length > MAX_LONG_SENTENCE_WORDS for length in sentence_lengths
        ),
        "heading_count": heading_count,
    }


def _normalise_heading(heading: str) -> str:
    """Compare headings by meaning-preserving typography, not fragile glyph choice."""
    normalized = unicodedata.normalize("NFKC", heading).lower()
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    return " ".join(normalized.strip().rstrip("?!:").split())


def _heading_aliases(topic: str) -> dict[str, set[str]]:
    """Allow a small set of pedagogical heading variants without weakening coverage."""
    simplified_topic = re.sub(r"^introduction to\s+", "", topic, flags=re.IGNORECASE)
    aliases = {
        "Start with a simple problem": {"A simple problem"},
        "Why does it matter": {f"Why does {simplified_topic} matter"},
        "How does it work": {f"How does {simplified_topic} work"},
    }
    concept_heading = expected_headings(topic)[2]
    if concept_heading.startswith("What is "):
        aliases[concept_heading] = {f"What is {simplified_topic}"}
    return aliases


def _heading_is_present(
    expected_heading: str, present_headings: set[str], topic: str
) -> bool:
    accepted = {expected_heading, *_heading_aliases(topic).get(expected_heading, set())}
    return any(_normalise_heading(heading) in present_headings for heading in accepted)


def _present_heading_names(lesson: str) -> set[str]:
    return {
        _normalise_heading(match.group(2))
        for match in _HEADING_PATTERN.finditer(lesson)
    }


def _section_text(lesson: str, section_name: str) -> str:
    """Extract a level-two section's content without relying on an LLM."""
    matches = list(_HEADING_PATTERN.finditer(lesson))
    target = _normalise_heading(section_name)
    for index, match in enumerate(matches):
        level = len(match.group(1))
        if level == 2 and _normalise_heading(match.group(2)) == target:
            section_end = len(lesson)
            for next_match in matches[index + 1 :]:
                if len(next_match.group(1)) <= 2:
                    section_end = next_match.start()
                    break
            return lesson[match.end() : section_end]
    return ""


def count_learner_questions(lesson: str) -> int:
    """Count only complete numbered learner questions in the required final section."""
    section = _section_text(lesson, "Check your understanding")
    return sum("?" in match.group(1) for match in _NUMBERED_QUESTION_PATTERN.finditer(section))


def _lesson_appears_truncated(lesson: str) -> bool:
    """Detect only structural end-of-output signals; never attempt grammar judgment."""
    stripped = lesson.rstrip()
    if not stripped:
        return False
    if len(_FENCED_CODE_PATTERN.findall(lesson)) % 2:
        return True
    if len(_UNESCAPED_DOLLAR_PATTERN.findall(lesson)) % 2:
        return True
    final_line = next((line.strip() for line in reversed(stripped.splitlines()) if line.strip()), "")
    return bool(_NUMBERED_QUESTION_PATTERN.match(final_line) and "?" not in final_line)


def run_static_checks(
    lesson: str,
    topic: str,
    *,
    attempt_number: int = 0,
    max_retries: int = 2,
) -> StaticEvaluation:
    """Validate hard, deterministic lesson invariants for one attempt."""
    diagnostics = calculate_diagnostics(lesson)
    failures: list[str] = []

    if not lesson.strip():
        failures.append("Lesson is empty.")

    if not HARD_MIN_WORDS <= diagnostics["word_count"] <= HARD_MAX_WORDS:
        failures.append(
            f"Lesson must contain {HARD_MIN_WORDS}-{HARD_MAX_WORDS} words; "
            f"found {diagnostics['word_count']}."
        )

    present_headings = _present_heading_names(lesson)
    missing_headings = [
        heading
        for heading in expected_headings(topic)
        if not _heading_is_present(heading, present_headings, topic)
    ]
    if missing_headings:
        failures.append("Missing required headings: " + ", ".join(missing_headings) + ".")

    learner_question_count = count_learner_questions(lesson)
    if learner_question_count < 3:
        failures.append(
            "Check your understanding must contain at least 3 questions; "
            f"found {learner_question_count}."
        )

    learner_section = _section_text(lesson, "Check your understanding")
    numbered_questions = list(_NUMBERED_QUESTION_PATTERN.finditer(learner_section))
    incomplete_questions = [
        question for question in numbered_questions if "?" not in question.group(1)
    ]
    if incomplete_questions:
        if (
            len(incomplete_questions) == 1
            and incomplete_questions[0] is numbered_questions[-1]
        ):
            failures.append(
                "Check your understanding contains an incomplete or truncated question."
            )
        else:
            failures.append("Each numbered learner question must contain a question mark.")

    if _lesson_appears_truncated(lesson):
        failures.append("Lesson appears incomplete or truncated near the end.")

    recap = _section_text(lesson, "Quick recap")
    if not recap.strip():
        failures.append("Quick recap must contain a short summary, not only its heading.")

    if not 0 <= attempt_number <= max_retries:
        failures.append(
            f"Attempt number {attempt_number} is outside the allowed 0-{max_retries} range."
        )

    return StaticEvaluation(
        passed=not failures,
        failures=failures,
        missing_headings=missing_headings,
        learner_question_count=learner_question_count,
        attempt_number=attempt_number,
        **diagnostics,
    )


def validate_gate_set(payload: SemanticEvaluation | dict[str, Any]) -> SemanticEvaluation:
    """Validate the exact, non-duplicated R1-R8 gate contract with Pydantic."""
    if isinstance(payload, SemanticEvaluation):
        return payload
    return SemanticEvaluation.model_validate(payload)


def semantic_evaluation_schema() -> dict[str, Any]:
    """Return a provider-friendly schema; Pydantic remains the final authority."""
    gate_ids = [f"R{number}" for number in range(1, 9)]
    gate_schema = {
        "type": "object",
        "properties": {
            "gate_id": {"type": "string", "enum": gate_ids},
            "name": {"type": "string"},
            "passed": {"type": "boolean"},
            "evidence": {"type": "string"},
            "reason": {"type": "string"},
            "required_fix": {"type": "string"},
        },
        "required": ["gate_id", "name", "passed", "evidence", "reason", "required_fix"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "gates": {
                "type": "array",
                "minItems": 8,
                "maxItems": 8,
                "items": gate_schema,
            }
        },
        "required": ["gates"],
        "additionalProperties": False,
    }


def build_failure_packet(
    attempt_number: int, evaluation: SemanticEvaluation
) -> FailurePacket | None:
    """Create transparent revision input from only the gates that failed."""
    failed_gates = [gate for gate in evaluation.gates if not gate.passed]
    if not failed_gates:
        return None
    return FailurePacket(attempt=attempt_number, failed_gates=failed_gates)


def run_semantic_evaluation(
    lesson: str,
    learner: LearnerProfile,
    canonical_facts: list[CanonicalFact],
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> SemanticEvaluation:
    """Run the invariant eight-gate critic with one format-only retry at most."""
    from prompts import build_semantic_evaluation_messages

    settings = settings or get_settings()
    messages = build_semantic_evaluation_messages(lesson, learner, canonical_facts)
    last_error: Exception | None = None
    for format_attempt in range(2):
        try:
            payload = call_json_model(
                messages,
                model=settings.evaluator_model,
                fallback_model=settings.evaluator_model_fallback,
                max_tokens=settings.evaluator_model_max_tokens,
                json_schema=semantic_evaluation_schema(),
                schema_name="semantic_evaluation",
                client=client,  # type: ignore[arg-type]
                settings=settings,
            )
            return validate_gate_set(payload)
        except ValidationError as error:
            last_error = error
        except LLMRequestError as error:
            if error.status_code is not None:
                raise SemanticEvaluationError("Semantic evaluation request failed.") from error
            last_error = error

        if format_attempt == 0:
            messages = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Your prior output did not satisfy the required schema. Return a "
                        "complete JSON object containing every R1-R8 gate exactly once."
                    ),
                },
            ]

    raise SemanticEvaluationError(
        "Semantic evaluator returned malformed structured output twice."
    ) from last_error
