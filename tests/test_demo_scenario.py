import json

from demo_scenario import DEMO_TRIGGER_TOPIC, deterministic_demo_enabled
from workflow import run_dynamic_workflow


def test_demo_trigger_is_strict(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DETERMINISTIC_DEMO", "true")
    assert deterministic_demo_enabled(DEMO_TRIGGER_TOPIC)
    assert not deterministic_demo_enabled("Introduction to RAG")
    assert not deterministic_demo_enabled("how does RAG help AI answer with facts?")


def test_demo_persists_two_attempts_without_memory_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DETERMINISTIC_DEMO", "true")
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    state = run_dynamic_workflow(DEMO_TRIGGER_TOPIC, run_id="demo")
    summary = json.loads((tmp_path / "runs" / "demo" / "run_summary.json").read_text())
    assert state["final_status"] == "READY_TO_SHIP"
    assert summary["mode"] == "deterministic_demo"
    assert summary["memory_write_enabled"] is False
    assert summary["attempt_count"] == 2
    assert [gate["gate_id"] for gate in summary["attempts"][0]["semantic_evaluation"]["gates"] if not gate["passed"]] == ["R3", "R4"]
    assert all(gate["passed"] for gate in summary["attempts"][1]["semantic_evaluation"]["gates"])


def test_demo_route_does_not_enter_live_workflow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENABLE_DETERMINISTIC_DEMO", "true")
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")

    def live_path_must_not_run(*args, **kwargs):
        raise AssertionError("The live research/model workflow must not run for the demo.")

    state = run_dynamic_workflow(
        DEMO_TRIGGER_TOPIC,
        run_id="no_live_calls",
        research_runner=live_path_must_not_run,
        memory_store=live_path_must_not_run,  # type: ignore[arg-type]
    )

    assert state["final_status"] == "READY_TO_SHIP"
