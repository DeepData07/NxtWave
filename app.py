"""Thin Streamlit demo for inspecting and running the lesson-quality workflow."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from config import RUNS_DIR
from memory import MemoryStore
from workflow import DemoFault, run_dynamic_workflow


FAULT_OPTIONS: dict[str, DemoFault] = {
    "None": "none",
    "RAG factual error (demo only)": "rag_factual_error",
    "Overly technical language (demo only)": "overly_technical_language",
    "Remove example section (demo only)": "remove_example_section",
}
GATE_IDS = [f"R{number}" for number in range(1, 9)]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def list_saved_runs(runs_directory: Path = RUNS_DIR) -> list[str]:
    """Return newest complete artifact directories first."""
    if not runs_directory.exists():
        return []
    run_directories = [
        path for path in runs_directory.iterdir() if path.is_dir() and (path / "run_summary.json").is_file()
    ]
    return [path.name for path in sorted(run_directories, key=lambda path: path.stat().st_mtime, reverse=True)]


def load_run_artifacts(run_id: str, runs_directory: Path = RUNS_DIR) -> dict[str, Any]:
    """Read a saved run without rerunning models or exposing environment settings."""
    run_directory = runs_directory / run_id
    summary = _read_json(run_directory / "run_summary.json", {})
    attempts = summary.get("attempts", [])
    for attempt in attempts:
        number = attempt.get("attempt_number")
        attempt["prompt"] = (run_directory / f"prompt_{number}.md").read_text(
            encoding="utf-8"
        ) if (run_directory / f"prompt_{number}.md").is_file() else ""
    return {
        "run_directory": run_directory,
        "summary": summary,
        "sources": _read_json(run_directory / "source_manifest.json", []),
        "rejection_log": _read_json(run_directory / "rejection_log.json", []),
        "loaded_guardrails": _read_json(run_directory / "loaded_guardrails.json", []),
        "memory_update": _read_json(run_directory / "memory_update.json", {}),
        "final_lesson": (run_directory / "final_lesson.md").read_text(encoding="utf-8")
        if (run_directory / "final_lesson.md").is_file()
        else "",
        "attempts": attempts,
    }


def gate_comparison(attempts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Create a diagnostic PASS/FAIL table; it is never a shipping average."""
    rows = [{"Gate": gate_id} for gate_id in GATE_IDS]
    for attempt in attempts:
        column = f"Attempt {int(attempt.get('attempt_number', 0)) + 1}"
        gates = {
            gate["gate_id"]: "PASS" if gate["passed"] else "FAIL"
            for gate in attempt.get("semantic_evaluation", {}).get("gates", [])
        }
        for row in rows:
            row[column] = gates.get(row["Gate"], "—")
    return rows


def diagnostics_table(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Attempt": int(attempt.get("attempt_number", 0)) + 1,
            "Static pass": attempt.get("static_evaluation", {}).get("passed", False),
            "Words": attempt.get("static_evaluation", {}).get("word_count", 0),
            "Average sentence length": attempt.get("static_evaluation", {}).get(
                "average_sentence_length", 0
            ),
            "Long sentences": attempt.get("static_evaluation", {}).get(
                "long_sentence_count", 0
            ),
            "Headings": attempt.get("static_evaluation", {}).get("heading_count", 0),
        }
        for attempt in attempts
    ]


def _render_status(artifacts: dict[str, Any]) -> None:
    summary = artifacts["summary"]
    attempts = artifacts["attempts"]
    if not summary:
        st.error("This run has no readable summary.")
        return
    final_status = summary.get("final_status", "UNKNOWN")
    if final_status == "READY_TO_SHIP":
        st.success(f"{final_status} — all hard checks passed.")
    elif final_status == "NEEDS_HUMAN_REVIEW":
        st.warning("NEEDS_HUMAN_REVIEW — retries ended while one or more hard checks still failed.")
    else:
        st.error(f"{final_status} — the workflow did not generate an ungrounded lesson.")

    st.caption(
        f"Run: {summary.get('run_id', 'unknown')} · Topic: {summary.get('topic', 'unknown')} · "
        f"Attempts: {len(attempts)}"
    )
    steps = ["Research planning", "Source discovery", "Source curation", "Knowledge pack built"]
    if attempts:
        steps.extend(["Lesson planned", "Evaluation complete"])
        steps.extend(f"Attempt {index + 1} generated" for index in range(len(attempts)))
    if len(attempts) > 1:
        steps.append("Retry triggered")
    steps.append("Ready to ship" if final_status == "READY_TO_SHIP" else final_status)
    st.markdown(" → ".join(steps))


def _render_sources(sources: list[dict[str, Any]]) -> None:
    st.subheader("Grounded sources")
    if not sources:
        st.info("No source manifest is available for this run.")
        return
    for source in sources:
        st.markdown(
            f"**{source.get('source_id', 'Source')} — {source.get('title', 'Untitled')}**  \n"
            f"{source.get('authority_type', 'Unknown authority')} · {source.get('domain', 'unknown domain')}  \n"
            f"[Open source]({source.get('url', '')})  \n"
            f"Why selected: {source.get('why_selected', 'No reason saved.')}"
        )


def _render_evaluation(attempts: list[dict[str, Any]]) -> None:
    st.subheader("Attempt comparison")
    st.dataframe(gate_comparison(attempts), use_container_width=True, hide_index=True)
    st.caption("This table is diagnostic only. Shipping remains Boolean: every hard check and gate must pass.")
    st.dataframe(diagnostics_table(attempts), use_container_width=True, hide_index=True)

    if attempts:
        selected = st.selectbox(
            "Show evaluation evidence for", attempts, format_func=lambda attempt: f"Attempt {attempt['attempt_number'] + 1}"
        )
        with st.expander("Gate evidence, reason, and required fix"):
            for gate in selected.get("semantic_evaluation", {}).get("gates", []):
                status = "PASS" if gate["passed"] else "FAIL"
                st.markdown(f"**{gate['gate_id']} — {status}: {gate['name']}**")
                st.write(f"Evidence: {gate['evidence']}")
                st.write(f"Reason: {gate['reason']}")
                st.write(f"Required fix: {gate['required_fix']}")
        with st.expander("Prompt used for this attempt"):
            st.code(selected.get("prompt", "No prompt snapshot available."), language="markdown")


def _render_memory(artifacts: dict[str, Any]) -> None:
    st.subheader("Cross-run learning memory")
    guardrails = artifacts["loaded_guardrails"]
    st.write(f"Loaded memory guardrails: {len(guardrails)}")
    if guardrails:
        st.dataframe(guardrails, use_container_width=True, hide_index=True)
    update = artifacts["memory_update"]
    if update:
        st.caption("This run's memory update")
        st.json(update)
    store = MemoryStore()
    st.dataframe(
        [{"Gate": gate_id, "Distinct failure runs": store.failure_count(gate_id)} for gate_id in GATE_IDS],
        use_container_width=True,
        hide_index=True,
    )


def _render_run(run_id: str) -> None:
    artifacts = load_run_artifacts(run_id)
    _render_status(artifacts)
    _render_sources(artifacts["sources"])
    _render_evaluation(artifacts["attempts"])

    st.subheader("Rejection log")
    st.json(artifacts["rejection_log"])
    _render_memory(artifacts)

    if artifacts["summary"].get("final_status") == "READY_TO_SHIP" and artifacts["final_lesson"]:
        st.subheader("Final passing lesson")
        st.markdown(artifacts["final_lesson"])
    elif artifacts["attempts"]:
        st.info("No final lesson is displayed because this run did not meet every hard shipping rule.")


def main() -> None:
    st.set_page_config(page_title="Lesson Quality Agent", layout="wide")
    st.title("NxtWave Lesson Quality Agent")
    st.caption("Dynamic grounding, hard gates, bounded correction, and auditable cross-run learning.")

    with st.sidebar:
        st.header("Run workflow")
        topic = st.text_input("Topic", value="Introduction to RAG")
        st.number_input("Maximum revisions", value=2, min_value=2, max_value=2, disabled=True)
        fault_label = st.selectbox("Demo fault", list(FAULT_OPTIONS))
        run_clicked = st.button("Generate / Run Workflow", type="primary")

    if run_clicked:
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        with st.status("Running grounded lesson workflow…", expanded=True) as status:
            st.write("Research planning and source discovery")
            st.write("Source curation and knowledge-pack construction")
            try:
                state = run_dynamic_workflow(
                    topic.strip(), run_id=run_id, demo_fault=FAULT_OPTIONS[fault_label]
                )
                st.write("Lesson generation, evaluation, and bounded revision")
                status.update(label=f"Workflow finished: {state['final_status']}", state="complete")
                st.session_state["selected_run"] = run_id
            except Exception as error:
                status.update(label="Workflow failed", state="error")
                st.exception(error)

    saved_runs = list_saved_runs()
    if not saved_runs:
        st.info("Run a workflow to create an inspectable artifact bundle.")
        return
    default_run = st.session_state.get("selected_run", saved_runs[0])
    selected_index = saved_runs.index(default_run) if default_run in saved_runs else 0
    selected_run = st.selectbox("Inspect saved run", saved_runs, index=selected_index)
    _render_run(selected_run)


if __name__ == "__main__":
    main()
