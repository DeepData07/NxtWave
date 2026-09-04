from __future__ import annotations

from evaluation import HARD_MIN_WORDS, calculate_diagnostics, expected_headings, run_static_checks
from tests.lesson_fixtures import TOPIC, good_lesson, short_lesson


def test_good_lesson_passes_all_static_checks() -> None:
    result = run_static_checks(good_lesson(), TOPIC)

    assert result.passed is True
    assert result.word_count >= HARD_MIN_WORDS
    assert result.learner_question_count == 3


def test_missing_example_section_is_rejected() -> None:
    lesson = good_lesson().replace("## Step-by-step example", "## Worked walkthrough")

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert "Step-by-step example" in result.missing_headings


def test_harmless_heading_typography_and_topic_variants_are_accepted() -> None:
    lesson = (
        good_lesson()
        .replace("## Start with a simple problem", "## A simple problem")
        .replace("## What is Introduction to RAG", "## What is RAG?")
        .replace("## Why does it matter", "## Why does RAG matter?")
        .replace("## How does it work", "## How does RAG work?")
        .replace("## Step-by-step example", "## Step‑by‑step example")
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is True
    assert result.missing_headings == []


def test_question_form_topic_does_not_create_a_duplicate_question_heading() -> None:
    headings = expected_headings("What is Cosine Similarity?")

    assert headings[0] == "What is Cosine Similarity?"
    assert headings[2] == "What does Cosine Similarity mean?"


def test_missing_recap_section_is_rejected() -> None:
    lesson = good_lesson().replace("## Quick recap", "## Final note")

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert "Quick recap" in result.missing_headings


def test_empty_recap_is_rejected_before_semantic_evaluation() -> None:
    lesson = good_lesson().replace(
        "## Quick recap\n\n" + " ".join([
            "This short explanation gives a beginner one clear practical idea, explains why "
            "it matters, and connects the idea to a safe useful learning goal today."
        ] * 5),
        "## Quick recap",
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert any("Quick recap must contain a short summary" in failure for failure in result.failures)


def test_too_short_lesson_is_rejected() -> None:
    result = run_static_checks(short_lesson(), TOPIC)

    assert result.passed is False
    assert any("700-2200 words" in failure for failure in result.failures)


def test_missing_learner_questions_is_rejected() -> None:
    lesson = good_lesson().replace(
        "1. What problem does this lesson describe?\n"
        "2. Why can this idea be useful?\n"
        "3. What is one limitation to remember?",
        "Review the lesson before continuing.",
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert result.learner_question_count == 0


def test_numbered_learner_prompts_without_question_marks_are_rejected() -> None:
    lesson = good_lesson().replace(
        "1. What problem does this lesson describe?\n"
        "2. Why can this idea be useful?\n"
        "3. What is one limitation to remember?",
        "1. Describe the problem from the lesson.\n"
        "2. Explain why the idea is useful.\n"
        "3. Name one limitation.",
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert result.learner_question_count == 0
    assert any("question mark" in failure for failure in result.failures)


def test_truncated_final_learner_question_is_rejected() -> None:
    lesson = good_lesson().replace(
        "3. What is one limitation to remember?",
        "3. What is one limitation to remem",
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert result.learner_question_count == 2
    assert "Check your understanding contains an incomplete or truncated question." in result.failures


def test_exact_truncated_rag_question_pattern_is_rejected() -> None:
    lesson = good_lesson().replace(
        "1. What problem does this lesson describe?\n"
        "2. Why can this idea be useful?\n"
        "3. What is one limitation to remember?",
        "1. Complete question?\n"
        "2. Complete question?\n"
        "3. Why can RAG provide m",
    )

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert result.learner_question_count == 2
    assert "Check your understanding contains an incomplete or truncated question." in result.failures


def test_unmatched_fenced_code_block_is_rejected() -> None:
    lesson = good_lesson() + "\n\n```python\nprint('unfinished')"

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert "Lesson appears incomplete or truncated near the end." in result.failures


def test_unmatched_canonical_math_delimiter_is_rejected() -> None:
    lesson = good_lesson() + "\n\n$A \\cdot B"

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert "Lesson appears incomplete or truncated near the end." in result.failures


def test_invalid_retry_count_is_rejected() -> None:
    result = run_static_checks(good_lesson(), TOPIC, attempt_number=3, max_retries=2)

    assert result.passed is False
    assert any("outside the allowed" in failure for failure in result.failures)


def test_diagnostics_flag_long_sentences_without_deciding_accessibility() -> None:
    long_sentence = " ".join(["word"] * 31) + "."

    diagnostics = calculate_diagnostics(long_sentence)

    assert diagnostics["long_sentence_count"] == 1
