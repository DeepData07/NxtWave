from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ui_server import create_app


def test_fastapi_adapter_starts_a_run_and_exposes_only_ui_safe_artifacts(tmp_path: Path) -> None:
    runs_directory = tmp_path / "runs"

    def fake_workflow(topic, *, run_id, max_retries, demo_fault, event_sink):
        artifact_directory = runs_directory / run_id
        artifact_directory.mkdir(parents=True)
        event = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "stage": "workflow",
            "status": "completed",
            "title": "READY TO SHIP",
            "detail": "Workflow complete.",
            "attempt": None,
        }
        (artifact_directory / "events.json").write_text(json.dumps([event]), encoding="utf-8")
        event_sink(event)
        (artifact_directory / "source_manifest.json").write_text(
            json.dumps([{"title": "Official docs", "domain": "example.org"}]), encoding="utf-8"
        )
        (artifact_directory / "memory_update.json").write_text(
            json.dumps({"recorded_gate_ids": []}), encoding="utf-8"
        )
        (artifact_directory / "attempt_0.md").write_text("# Lesson", encoding="utf-8")
        (artifact_directory / "run_summary.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "topic": topic,
                    "final_status": "READY_TO_SHIP",
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "attempt_number": 0,
                            "static_evaluation": {"passed": True, "word_count": 800},
                            "semantic_evaluation": {
                                "gates": [
                                    {"gate_id": f"R{number}", "passed": True}
                                    for number in range(1, 9)
                                ]
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {"final_status": "READY_TO_SHIP"}

    with TestClient(create_app(runs_directory=runs_directory, workflow_runner=fake_workflow)) as client:
        created = client.post(
            "/api/runs",
            json={"topic": "Introduction to RAG", "max_revisions": 2, "demo_fault": "none"},
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        for _ in range(30):
            run = client.get(f"/api/runs/{run_id}").json()
            if run["run"]["status"] != "RUNNING":
                break
            time.sleep(0.01)

        assert run["run"]["status"] == "READY_TO_SHIP"
        assert client.get(f"/api/runs/{run_id}/attempts/1").json()["lesson"] == "# Lesson"
        assert client.get(f"/api/runs/{run_id}/sources").json()["source_count"] == 1
        assert client.get(f"/api/runs/{run_id}/memory").status_code == 200
        assert "READY TO SHIP" in client.get(f"/api/runs/{run_id}/events").text
        assert any(item["id"] == run_id for item in client.get("/api/runs").json())
        homepage = client.get("/")
        assert "NxtWave Lesson Quality Agent" in homepage.text
        assert 'src="/ui/assets/' in homepage.text
        assert client.get("/assets/not-a-real-file.js").status_code == 404
