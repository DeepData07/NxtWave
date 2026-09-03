from __future__ import annotations

from main import main


def test_cli_passes_topic_fault_and_run_id_to_workflow(capsys) -> None:
    captured: dict[str, str] = {}

    def fake_workflow(topic: str, *, run_id: str, demo_fault: str):
        captured.update(topic=topic, run_id=run_id, demo_fault=demo_fault)
        return {"final_status": "READY_TO_SHIP"}

    exit_code = main(
        ["--topic", "Introduction to RAG", "--fault", "rag_factual_error", "--run-id", "demo"],
        workflow_runner=fake_workflow,
    )

    assert exit_code == 0
    assert captured == {
        "topic": "Introduction to RAG",
        "run_id": "demo",
        "demo_fault": "rag_factual_error",
    }
    assert "READY_TO_SHIP" in capsys.readouterr().out
