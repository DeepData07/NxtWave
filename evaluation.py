"""Deterministic lesson checks and readability diagnostics.

Semantic quality remains a later LLM-evaluation stage. This module deliberately
uses only normal Python for measurable constraints.
"""

from __future__ import annotations

import re

from models import StaticEvaluation


HARD_MIN_WORDS = 700
HARD_MAX_WORDS = 2200
MAX_LONG_SENTENCE_WORDS = 30

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WORD_PATTERN = re.compile(r"\b[\w'-]+\b")
_SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")


def expected_headings(topic: str) -> list[str]:
    """Return the predictable heading contract for a lesson topic."""
    return [
        topic,
        "Start with a simple problem",
        f"What is {topic}",
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
    return " ".join(heading.lower().strip().rstrip("?!:").split())


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
    """Count question marks in the designated learner-check section."""
    section = _section_text(lesson, "Check your understanding")
    return section.count("?")


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
        if _normalise_heading(heading) not in present_headings
    ]
    if missing_headings:
        failures.append("Missing required headings: " + ", ".join(missing_headings) + ".")

    learner_question_count = count_learner_questions(lesson)
    if learner_question_count < 3:
        failures.append(
            "Check your understanding must contain at least 3 questions; "
            f"found {learner_question_count}."
        )

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
