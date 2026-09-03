"""Small SQLite memory for auditable cross-run lesson-quality guardrails."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from config import MEMORY_DB_PATH, Settings, get_settings
from llm import LLMRequestError, call_json_model
from models import AttemptRecord, GateId, LearnedGuardrail
from prompts import build_guardrail_distillation_messages


class GuardrailDraft(BaseModel):
    """The strictly bounded result of one fast-model distillation call."""

    model_config = ConfigDict(extra="forbid")

    rule: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class FailureExample:
    gate_id: GateId
    evidence: str
    reason: str
    required_fix: str


@dataclass(frozen=True)
class MemoryUpdate:
    recorded_gate_ids: list[GateId] = field(default_factory=list)
    promoted_guardrails: list[LearnedGuardrail] = field(default_factory=list)
    distillation_errors: list[str] = field(default_factory=list)


GuardrailDistiller = Callable[[GateId, list[FailureExample]], str]


class MemoryStore:
    """SQLite-backed, process-restart-safe storage with one failure per run/gate."""

    def __init__(self, database_path: Path = MEMORY_DB_PATH) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS gate_failures (
                    run_id TEXT NOT NULL,
                    gate_id TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    required_fix TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, gate_id)
                );

                CREATE TABLE IF NOT EXISTS learned_guardrails (
                    guardrail_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gate_id TEXT NOT NULL UNIQUE,
                    rule TEXT NOT NULL,
                    source_run_count INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def record_failure(self, run_id: str, failure: FailureExample) -> bool:
        """Record one gate failure; duplicate attempts in a run do not increase the count."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO gate_failures
                    (run_id, gate_id, evidence, reason, required_fix)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    failure.gate_id,
                    failure.evidence,
                    failure.reason,
                    failure.required_fix,
                ),
            )
        return cursor.rowcount == 1

    def failure_count(self, gate_id: GateId) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT run_id) AS count FROM gate_failures WHERE gate_id = ?",
                (gate_id,),
            ).fetchone()
        return int(row["count"])

    def failure_examples(self, gate_id: GateId, limit: int = 3) -> list[FailureExample]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT gate_id, evidence, reason, required_fix
                FROM gate_failures
                WHERE gate_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (gate_id, limit),
            ).fetchall()
        return [
            FailureExample(
                gate_id=row["gate_id"],
                evidence=row["evidence"],
                reason=row["reason"],
                required_fix=row["required_fix"],
            )
            for row in rows
        ]

    def guardrail_for_gate(self, gate_id: GateId) -> LearnedGuardrail | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM learned_guardrails WHERE gate_id = ?", (gate_id,)
            ).fetchone()
        return self._row_to_guardrail(row) if row else None

    def save_guardrail(
        self, gate_id: GateId, rule: str, source_run_count: int
    ) -> LearnedGuardrail:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learned_guardrails (gate_id, rule, source_run_count, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(gate_id) DO UPDATE SET
                    rule = excluded.rule,
                    source_run_count = excluded.source_run_count,
                    active = 1
                """,
                (gate_id, rule.strip(), source_run_count),
            )
            row = connection.execute(
                "SELECT * FROM learned_guardrails WHERE gate_id = ?", (gate_id,)
            ).fetchone()
        return self._row_to_guardrail(row)

    def active_guardrails(self, limit: int = 5) -> list[LearnedGuardrail]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learned_guardrails
                WHERE active = 1
                ORDER BY source_run_count DESC, guardrail_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_guardrail(row) for row in rows]

    @staticmethod
    def _row_to_guardrail(row: sqlite3.Row) -> LearnedGuardrail:
        return LearnedGuardrail(
            guardrail_id=row["guardrail_id"],
            gate_id=row["gate_id"],
            rule=row["rule"],
            source_run_count=row["source_run_count"],
            active=bool(row["active"]),
        )


def distill_guardrail(
    gate_id: GateId,
    examples: list[FailureExample],
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> str:
    """Use the fast model once to turn repeated evidence into one reusable rule."""
    settings = settings or get_settings()
    payload = call_json_model(
        build_guardrail_distillation_messages(gate_id, examples),
        model=settings.fast_model,
        fallback_model=settings.fast_model_fallback,
        max_tokens=settings.memory_distillation_max_tokens,
        json_schema=GuardrailDraft.model_json_schema(),
        schema_name="learned_guardrail",
        client=client,  # type: ignore[arg-type]
        settings=settings,
    )
    return GuardrailDraft.model_validate(payload).rule


def _first_failure_per_gate(attempts: Iterable[AttemptRecord]) -> dict[GateId, FailureExample]:
    failures: dict[GateId, FailureExample] = {}
    for attempt in attempts:
        if attempt.semantic_evaluation is None:
            continue
        for gate in attempt.semantic_evaluation.gates:
            if not gate.passed and gate.gate_id not in failures:
                failures[gate.gate_id] = FailureExample(
                    gate_id=gate.gate_id,
                    evidence=gate.evidence,
                    reason=gate.reason,
                    required_fix=gate.required_fix,
                )
    return failures


def update_memory_from_attempts(
    store: MemoryStore,
    run_id: str,
    attempts: Iterable[AttemptRecord],
    *,
    threshold: int,
    distiller: GuardrailDistiller,
) -> MemoryUpdate:
    """Persist recurring semantic failures and promote only after distinct-run evidence."""
    if threshold < 2:
        raise ValueError("Guardrail promotion threshold must be at least 2")

    recorded: list[GateId] = []
    promoted: list[LearnedGuardrail] = []
    errors: list[str] = []
    for gate_id, failure in _first_failure_per_gate(attempts).items():
        if store.record_failure(run_id, failure):
            recorded.append(gate_id)
        count = store.failure_count(gate_id)
        existing = store.guardrail_for_gate(gate_id)
        if existing is not None:
            store.save_guardrail(gate_id, existing.rule, count)
            continue
        if count < threshold:
            continue
        try:
            rule = distiller(gate_id, store.failure_examples(gate_id))
            promoted.append(store.save_guardrail(gate_id, rule, count))
        except (LLMRequestError, ValueError) as error:
            errors.append(f"{gate_id}: {error}")
    return MemoryUpdate(recorded, promoted, errors)
