"""Local lesson fixtures for fast deterministic evaluator tests."""

from __future__ import annotations


TOPIC = "Introduction to RAG"
_PARAGRAPH = (
    "This short explanation gives a beginner one clear practical idea, explains why "
    "it matters, and connects the idea to a safe useful learning goal today."
)


def good_lesson() -> str:
    sections = [
        "Start with a simple problem",
        f"What is {TOPIC}?",
        "Why does it matter?",
        "How does it work?",
        "Step-by-step example",
        "Important terms",
        "Limitations",
        "Quick recap",
    ]
    lesson_parts = [f"# {TOPIC}"]
    for heading in sections:
        lesson_parts.append(
            f"## {heading}\n\n" + " ".join([_PARAGRAPH] * 5)
        )
    lesson_parts.append(
        "## Check your understanding\n\n"
        "1. What problem does this lesson describe?\n"
        "2. Why can this idea be useful?\n"
        "3. What is one limitation to remember?"
    )
    return "\n\n".join(lesson_parts)


def short_lesson() -> str:
    headings = [
        f"# {TOPIC}",
        "## Start with a simple problem",
        f"## What is {TOPIC}?",
        "## Why does it matter?",
        "## How does it work?",
        "## Step-by-step example",
        "## Important terms",
        "## Limitations",
        "## Quick recap",
        "## Check your understanding",
    ]
    return "\n\n".join(headings + ["One? Two? Three?"])
