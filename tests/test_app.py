from __future__ import annotations

import json
from pathlib import Path

from app import diagnostics_table, gate_comparison, list_saved_runs, load_run_artifacts


def test_saved_run_artifacts_are_loaded_for_the_demo(tmp_path: Path) -> None:
    run_directory = tmp_path / "runs" / "demo_run"
    run_directory.mkdir(parents=True)
    summary = {
        "run_id": "demo_run",
        "topic": "Introduction to RAG",
        "final_status": "READY_TO_SHIP",
        "attempts": [
            {
                "attempt_number": 0,
                "static_evaluation": {
                    "passed": True,
                    "word_count": 900,
                    "average_sentence_length": 15,
                    "long_sentence_count": 2,
                    "heading_count": 10,
                },
                "semantic_evaluation": {
                    "gates": [
                        {"gate_id": f"R{number}", "passed": True} for number in range(1, 9)
                    ]
                },
            }
        ],
    }
    (run_directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_directory / "prompt_0.md").write_text("# Prompt", encoding="utf-8")
    (run_directory / "workflow_error.json").write_text(
        json.dumps({"message": "Saved provider error"}), encoding="utf-8"
    )

    assert list_saved_runs(tmp_path / "runs") == ["demo_run"]
    artifacts = load_run_artifacts("demo_run", tmp_path / "runs")

    assert artifacts["summary"]["final_status"] == "READY_TO_SHIP"
    assert artifacts["attempts"][0]["prompt"] == "# Prompt"
    assert artifacts["workflow_error"]["message"] == "Saved provider error"
    assert gate_comparison(artifacts["attempts"])[0]["Attempt 1"] == "PASS"
    assert diagnostics_table(artifacts["attempts"])[0]["Words"] == 900
