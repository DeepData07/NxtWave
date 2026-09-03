from __future__ import annotations

from evaluation import HARD_MIN_WORDS, calculate_diagnostics, run_static_checks
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


def test_missing_recap_section_is_rejected() -> None:
    lesson = good_lesson().replace("## Quick recap", "## Final note")

    result = run_static_checks(lesson, TOPIC)

    assert result.passed is False
    assert "Quick recap" in result.missing_headings


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


def test_invalid_retry_count_is_rejected() -> None:
    result = run_static_checks(good_lesson(), TOPIC, attempt_number=3, max_retries=2)

    assert result.passed is False
    assert any("outside the allowed" in failure for failure in result.failures)


def test_diagnostics_flag_long_sentences_without_deciding_accessibility() -> None:
    long_sentence = " ".join(["word"] * 31) + "."

    diagnostics = calculate_diagnostics(long_sentence)

    assert diagnostics["long_sentence_count"] == 1
