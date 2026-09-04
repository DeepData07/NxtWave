from __future__ import annotations

import json
from pathlib import Path

from ui_contract import load_run_view
from workflow import RunEventRecorder


def test_ui_contract_makes_legacy_artifacts_clear_without_rewriting_them(tmp_path: Path) -> None:
    run_directory = tmp_path / "runs" / "demo"
    run_directory.mkdir(parents=True)
    summary = {
        "run_id": "demo",
        "topic": "What is Cosine Similarity?",
        "final_status": "READY_TO_SHIP",
        "attempts": [
            {
                "attempt_number": 0,
                "static_evaluation": {
                    "passed": False,
                    "word_count": 900,
                    "heading_count": 9,
                    "learner_question_count": 1,
                    "average_sentence_length": 20,
                    "long_sentence_count": 5,
                    "failures": ["Need three learner questions."],
                },
                "semantic_evaluation": {
                    "gates": [
                        {
                            "gate_id": f"R{number}",
                            "passed": number != 8,
                            "name": "Raw name",
                            "evidence": "Evidence",
                            "reason": "Reason",
                            "required_fix": "Add questions.",
                        }
                        for number in range(1, 9)
                    ]
                },
            },
            {
                "attempt_number": 1,
                "static_evaluation": {
                    "passed": True,
                    "word_count": 950,
                    "heading_count": 9,
                    "learner_question_count": 3,
                    "average_sentence_length": 15,
                    "long_sentence_count": 2,
                },
                "semantic_evaluation": {
                    "gates": [
                        {
                            "gate_id": f"R{number}",
                            "passed": True,
                            "name": "Raw name",
                            "evidence": "Evidence",
                            "reason": "Reason",
                            "required_fix": "No fix required.",
                        }
                        for number in range(1, 9)
                    ]
                },
            },
        ],
    }
    (run_directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_directory / "attempt_0.md").write_text("# First lesson", encoding="utf-8")
    (run_directory / "attempt_1.md").write_text("# Final lesson", encoding="utf-8")
    (run_directory / "source_manifest.json").write_text(
        json.dumps([{"title": "Official source", "domain": "example.org"}]), encoding="utf-8"
    )
    (run_directory / "canonical_facts.json").write_text(json.dumps([{"fact_id": "FACT_001"}]), encoding="utf-8")

    view = load_run_view("demo", tmp_path / "runs")

    assert view["run"]["status"] == "READY_TO_SHIP"
    assert view["attempts"][0]["status"] == "REJECTED"
    assert view["attempts"][0]["failed_gates"][0]["label"] == "Standalone & Complete"
    assert view["attempts"][1]["status"] == "PASSED"
    assert view["final_lesson"] == "# Final lesson"
    assert view["grounding"]["source_count"] == 1
    assert view["retry_changes"][0]["resolved_gates"][0]["id"] == "R8"
    assert any(event["status"] == "retry" for event in view["events"])


def test_event_recorder_persists_before_notifying_a_ui_listener(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    delivered: list[dict] = []

    recorder = RunEventRecorder("event_demo", delivered.append)
    recorder.emit(
        stage="source_discovery",
        status="completed",
        title="Source discovery complete",
        detail="12 candidate sources found",
    )

    events = json.loads((tmp_path / "runs" / "event_demo" / "events.json").read_text())
    assert events == delivered
    assert events[0]["title"] == "Source discovery complete"


def test_ui_contract_exposes_a_generated_draft_while_evaluation_is_running(tmp_path: Path) -> None:
    run_directory = tmp_path / "runs" / "in_progress"
    run_directory.mkdir(parents=True)
    (run_directory / "attempt_0.md").write_text("# Draft lesson", encoding="utf-8")

    view = load_run_view("in_progress", tmp_path / "runs")

    assert view["attempts"][0]["status"] == "EVALUATING"
    assert view["attempts"][0]["lesson"] == "# Draft lesson"
