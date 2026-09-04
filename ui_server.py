"""Thin FastAPI adapter for the existing lesson-quality workflow.

It owns HTTP and background-thread concerns only. LangGraph, research,
evaluation, retries, memory, and artifact persistence remain in their existing
backend modules.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import PROJECT_ROOT, RUNS_DIR
from ui_contract import list_run_ids, load_run_view
from workflow import DemoFault, WorkflowData, run_dynamic_workflow


UI_DIRECTORY = PROJECT_ROOT / "ui"
RunWorkflow = Callable[..., WorkflowData]


class StartRunRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    max_revisions: int = Field(default=2, ge=0, le=2)
    demo_fault: DemoFault = "none"


@dataclass
class ActiveRun:
    run_id: str
    topic: str
    max_revisions: int
    demo_fault: DemoFault
    status: str = "RUNNING"
    current_step: str = "Queued"
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunRegistry:
    """Small in-process registry; persistent artifacts remain the source of truth."""

    def __init__(self, runs_directory: Path, workflow_runner: RunWorkflow) -> None:
        self.runs_directory = runs_directory
        self.workflow_runner = workflow_runner
        self._runs: dict[str, ActiveRun] = {}
        self._lock = threading.Lock()

    def start(self, request: StartRunRequest) -> ActiveRun:
        run_id = f"ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        active = ActiveRun(
            run_id=run_id,
            topic=request.topic.strip(),
            max_revisions=request.max_revisions,
            demo_fault=request.demo_fault,
        )
        with self._lock:
            self._runs[run_id] = active
        thread = threading.Thread(target=self._run, args=(active,), daemon=True, name=run_id)
        thread.start()
        return active

    def get(self, run_id: str) -> ActiveRun | None:
        with self._lock:
            active = self._runs.get(run_id)
            return None if active is None else ActiveRun(**active.__dict__)

    def active_runs(self) -> list[ActiveRun]:
        with self._lock:
            return [ActiveRun(**active.__dict__) for active in self._runs.values()]

    def _on_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            active = self._runs.get(run_id)
            if active is not None:
                active.current_step = event.get("title", active.current_step)

    def _run(self, active: ActiveRun) -> None:
        try:
            state = self.workflow_runner(
                active.topic,
                run_id=active.run_id,
                max_retries=active.max_revisions,
                demo_fault=active.demo_fault,
                event_sink=lambda event: self._on_event(active.run_id, event),
            )
            with self._lock:
                active.status = state.get("final_status", "NEEDS_HUMAN_REVIEW")
                active.current_step = active.status.replace("_", " ")
        except Exception as error:  # Keep unexpected adapter failures inspectable without traces.
            with self._lock:
                active.status = "FAILED"
                active.current_step = "Workflow failed"
                active.error = str(error)


def _view_for_run(registry: RunRegistry, run_id: str) -> dict[str, Any]:
    active = registry.get(run_id)
    saved = run_id in list_run_ids(registry.runs_directory)
    if active is None and not saved:
        raise HTTPException(status_code=404, detail="Run not found.")
    view = load_run_view(run_id, registry.runs_directory)
    if active is not None:
        view["run"].update(
            {
                "id": active.run_id,
                "topic": active.topic,
                "status": active.status,
                "max_revisions": active.max_revisions,
                "current_step": active.current_step,
                "started_at": active.started_at,
                "error": active.error or view["run"].get("error"),
            }
        )
    return view


def _sse_frame(index: int, event: dict[str, Any]) -> str:
    return f"id: {index}\nevent: workflow\ndata: {json.dumps(event)}\n\n"


def create_app(
    *,
    runs_directory: Path = RUNS_DIR,
    workflow_runner: RunWorkflow = run_dynamic_workflow,
) -> FastAPI:
    """Create a testable FastAPI app without changing workflow business logic."""
    registry = RunRegistry(runs_directory, workflow_runner)
    app = FastAPI(title="NxtWave Lesson Quality Agent UI", docs_url=None, redoc_url=None)
    app.state.registry = registry
    UI_DIRECTORY.mkdir(exist_ok=True)
    app.mount("/ui", StaticFiles(directory=str(UI_DIRECTORY)), name="ui")

    @app.get("/", include_in_schema=False)
    def index():
        index_path = UI_DIRECTORY / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse("<p>NxtWave UI Stage 2 adapter is running. The browser workspace arrives in Stage 3.</p>")

    @app.post("/api/runs", status_code=202)
    def start_run(request: StartRunRequest) -> dict[str, str]:
        active = registry.start(request)
        return {"run_id": active.run_id, "status": active.status}

    @app.get("/api/runs")
    def recent_runs() -> list[dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for run_id in list_run_ids(runs_directory):
            view = load_run_view(run_id, runs_directory)
            results[run_id] = view["run"]
        for active in registry.active_runs():
            results[active.run_id] = {
                "id": active.run_id,
                "topic": active.topic,
                "status": active.status,
                "attempt_count": 0,
                "current_step": active.current_step,
                "started_at": active.started_at,
            }
        return list(results.values())

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return _view_for_run(registry, run_id)

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> StreamingResponse:
        _view_for_run(registry, run_id)
        try:
            next_index = int(request.headers.get("last-event-id", "-1")) + 1
        except ValueError:
            next_index = 0

        async def event_stream():
            nonlocal next_index
            while True:
                view = _view_for_run(registry, run_id)
                events = view["events"]
                while next_index < len(events):
                    yield _sse_frame(next_index, events[next_index])
                    next_index += 1
                active = registry.get(run_id)
                if active is None or active.status != "RUNNING":
                    break
                if await request.is_disconnected():
                    break
                await asyncio.sleep(0.2)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/attempts/{attempt_number}")
    def get_attempt(run_id: str, attempt_number: int) -> dict[str, Any]:
        view = _view_for_run(registry, run_id)
        for attempt in view["attempts"]:
            if attempt["number"] == attempt_number:
                return attempt
        raise HTTPException(status_code=404, detail="Attempt not available yet.")

    @app.get("/api/runs/{run_id}/sources")
    def get_sources(run_id: str) -> dict[str, Any]:
        return _view_for_run(registry, run_id)["grounding"]

    @app.get("/api/runs/{run_id}/memory")
    def get_memory(run_id: str) -> dict[str, Any]:
        return _view_for_run(registry, run_id)["memory"]

    return app


app = create_app()
