"""Read-only, presentation-safe views of persisted lesson workflow artifacts.

This module intentionally contains no workflow decisions. It only normalizes the
already persisted run data into a compact contract for the future browser UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import RUNS_DIR


GATE_LABELS = {
    "R1": "Factual Accuracy",
    "R2": "Essential Coverage",
    "R3": "Beginner Accessibility",
    "R4": "Jargon Explained",
    "R5": "Learning by Example",
    "R6": "Teaching Flow",
    "R7": "Appropriate Depth",
    "R8": "Standalone & Complete",
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def list_run_ids(runs_directory: Path = RUNS_DIR) -> list[str]:
    """Return completed/inspectable runs newest first without exposing paths."""
    if not runs_directory.exists():
        return []
    runs = [
        path
        for path in runs_directory.iterdir()
        if path.is_dir() and (path / "run_summary.json").is_file()
    ]
    return [path.name for path in sorted(runs, key=lambda path: path.stat().st_mtime, reverse=True)]


def _normalise_attempt(run_directory: Path, payload: dict[str, Any]) -> dict[str, Any]:
    number = int(payload.get("attempt_number", 0))
    static = payload.get("static_evaluation") or _read_json(
        run_directory / f"static_evaluation_{number}.json", {}
    )
    semantic = payload.get("semantic_evaluation") or _read_json(
        run_directory / f"evaluation_{number}.json", {}
    )
    gates = []
    for gate in semantic.get("gates", []):
        gate_id = gate.get("gate_id", "")
        gates.append(
            {
                "id": gate_id,
                "label": GATE_LABELS.get(gate_id, gate.get("name", gate_id)),
                "passed": bool(gate.get("passed", False)),
                "evidence": gate.get("evidence", ""),
                "reason": gate.get("reason", ""),
                "required_fix": gate.get("required_fix", ""),
            }
        )
    failed_gates = [gate for gate in gates if not gate["passed"]]
    has_static_evaluation = bool(static)
    has_semantic_evaluation = bool(semantic)
    static_pass = bool(static.get("passed", False))
    semantic_pass = bool(gates) and not failed_gates
    return {
        "number": number + 1,
        "status": (
            "EVALUATING"
            if not has_static_evaluation or not has_semantic_evaluation
            else "PASSED" if static_pass and semantic_pass else "REJECTED"
        ),
        "lesson": _read_text(run_directory / f"attempt_{number}.md"),
        "prompt_kind": payload.get("prompt_kind", "initial"),
        "gates": gates,
        "failed_gates": failed_gates,
        "static_checks": {
            "passed": static_pass,
            "word_count": static.get("word_count", 0),
            "required_sections": static.get("heading_count", 0),
            "missing_headings": static.get("missing_headings", []),
            "learner_questions": static.get("learner_question_count", 0),
            "failures": static.get("failures", []),
            "average_sentence_length": static.get("average_sentence_length", 0),
            "long_sentence_count": static.get("long_sentence_count", 0),
        },
        "raw_evaluation": semantic,
        "raw_static_evaluation": static,
        "prompt": _read_text(run_directory / f"prompt_{number}.md"),
    }


def _derived_events(
    summary: dict[str, Any], sources: list[dict[str, Any]], facts: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Make legacy saved runs inspectable even though they predate events.json."""
    events: list[dict[str, Any]] = []

    def add(status: str, title: str, detail: str = "", attempt: int | None = None) -> None:
        events.append(
            {
                "timestamp": "",
                "stage": "legacy_artifact",
                "status": status,
                "title": title,
                "detail": detail,
                "attempt": attempt,
            }
        )

    if sources or facts:
        add("completed", "Research and grounding completed")
        add("completed", "Authoritative sources selected", f"{len(sources)} sources selected")
        add("completed", "Grounded facts built", f"{len(facts)} canonical facts extracted")
    for attempt_data in attempts:
        number = attempt_data["number"]
        add("completed", f"Attempt {number} generated", attempt=number - 1)
        passed = sum(gate["passed"] for gate in attempt_data["gates"])
        add(
            "completed" if attempt_data["status"] == "PASSED" else "failed",
            f"Attempt {number} {'passed' if attempt_data['status'] == 'PASSED' else 'rejected'}",
            f"{passed}/8 semantic gates passed",
            attempt=number - 1,
        )
        if attempt_data["status"] == "REJECTED" and number < len(attempts):
            add("retry", "Targeted revision requested", attempt=number)
    final_status = summary.get("final_status", "")
    if final_status:
        add(
            "completed" if final_status == "READY_TO_SHIP" else "failed",
            final_status.replace("_", " "),
        )
    return events


def _retry_changes(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for previous, current in zip(attempts, attempts[1:]):
        previous_failures = {gate["id"]: gate for gate in previous["failed_gates"]}
        current_failure_ids = {gate["id"] for gate in current["failed_gates"]}
        resolved = [
            {
                "id": gate_id,
                "label": gate["label"],
                "targeted_fix": gate["required_fix"],
            }
            for gate_id, gate in previous_failures.items()
            if gate_id not in current_failure_ids
        ]
        diagnostics: list[dict[str, Any]] = []
        for key, label in (
            ("average_sentence_length", "Average sentence length"),
            ("long_sentence_count", "Long sentences"),
            ("learner_questions", "Learner questions"),
        ):
            before = previous["static_checks"][key]
            after = current["static_checks"][key]
            if before != after:
                diagnostics.append({"label": label, "before": before, "after": after})
        changes.append(
            {
                "from_attempt": previous["number"],
                "to_attempt": current["number"],
                "resolved_gates": resolved,
                "supporting_diagnostics": diagnostics,
            }
        )
    return changes


def load_run_view(run_id: str, runs_directory: Path = RUNS_DIR) -> dict[str, Any]:
    """Return the compact, safe data contract consumed by the future UI."""
    run_directory = runs_directory / run_id
    summary = _read_json(run_directory / "run_summary.json", {})
    sources = _read_json(run_directory / "source_manifest.json", [])
    facts = _read_json(run_directory / "canonical_facts.json", [])
    attempt_payloads = summary.get("attempts", [])
    if not attempt_payloads:
        attempt_payloads = [
            {"attempt_number": int(path.stem.removeprefix("attempt_"))}
            for path in sorted(run_directory.glob("attempt_*.md"))
        ]
    attempts = [_normalise_attempt(run_directory, item) for item in attempt_payloads]
    loaded_guardrails = _read_json(run_directory / "loaded_guardrails.json", [])
    memory_update = _read_json(run_directory / "memory_update.json", {})
    stored_events = _read_json(run_directory / "events.json", [])
    events = stored_events if isinstance(stored_events, list) and stored_events else _derived_events(
        summary, sources, facts, attempts
    )
    final_lesson = _read_text(run_directory / "final_lesson.md")
    if not final_lesson and attempts:
        final_lesson = attempts[-1]["lesson"]
    return {
        "run": {
            "id": run_id,
            "topic": summary.get("topic", ""),
            "status": summary.get("final_status", "UNKNOWN"),
            "attempt_count": len(attempts),
            "error": summary.get("error"),
        },
        "events": events,
        "attempts": attempts,
        "retry_changes": _retry_changes(attempts),
        "grounding": {
            "source_count": len(sources),
            "fact_count": len(facts),
            "sources": [
                {
                    "id": source.get("source_id", ""),
                    "title": source.get("title", ""),
                    "authority_type": source.get("authority_type", ""),
                    "domain": source.get("domain", ""),
                    "selection_reason": source.get("selection_reason", ""),
                    "url": source.get("url", ""),
                }
                for source in sources
            ],
        },
        "memory": {
            "loaded_guardrail_count": len(loaded_guardrails),
            "recorded_gate_ids": memory_update.get("recorded_gate_ids", []),
            "promoted_guardrails": memory_update.get("promoted_guardrails", []),
            "skipped": memory_update.get("skipped"),
        },
        "final_lesson": final_lesson,
        "workflow_error": _read_json(run_directory / "workflow_error.json", {}),
        "advanced": {
            "rejection_log": _read_json(run_directory / "rejection_log.json", []),
            "canonical_facts": facts,
            "artifact_names": sorted(path.name for path in run_directory.iterdir()) if run_directory.exists() else [],
        },
    }
