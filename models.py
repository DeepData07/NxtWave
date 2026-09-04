"""Shared Pydantic contracts for the lesson-quality workflow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


GateId = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
EXPECTED_GATE_IDS: frozenset[str] = frozenset(
    {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"}
)


class LearnerProfile(BaseModel):
    education: str = "12th-grade graduate"
    region: str = "India"
    english_level: str = "limited"
    technical_background: str = "none"
    goal: str = "start an AI career"


class ResearchPlan(BaseModel):
    canonical_topic: str = Field(min_length=1)
    learning_scope: list[str] = Field(min_length=1, max_length=8)
    search_queries: list[str] = Field(min_length=2, max_length=3)


class SearchCandidate(BaseModel):
    candidate_id: str = Field(pattern=r"^CAND_\d{3}$")
    title: str = Field(min_length=1)
    url: HttpUrl
    content: str = ""


class SelectedSource(SearchCandidate):
    source_id: str = Field(pattern=r"^SRC_\d{3}$")
    domain: str = Field(min_length=1)
    authority_type: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)


class SourceChoice(BaseModel):
    candidate_id: str = Field(pattern=r"^CAND_\d{3}$")
    authority_type: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)


class SourceCuration(BaseModel):
    selections: list[SourceChoice] = Field(min_length=1, max_length=4)


class FactEvidence(BaseModel):
    source_id: str = Field(pattern=r"^SRC_\d{3}$")
    excerpt: str = Field(min_length=1, max_length=300)


class CanonicalFact(BaseModel):
    fact_id: str = Field(pattern=r"^FACT_\d{3}$")
    concept: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    supported_by: list[str] = Field(min_length=1)
    status: Literal["supported", "single_source", "conflicting"] = "supported"
    evidence: list[FactEvidence] = Field(default_factory=list)


class LessonPlan(BaseModel):
    title: str = Field(min_length=1)
    sections: list[str] = Field(min_length=1)


class StaticEvaluation(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)
    missing_headings: list[str] = Field(default_factory=list)
    learner_question_count: int = Field(ge=0, default=0)
    attempt_number: int = Field(ge=0, default=0)
    word_count: int = Field(ge=0)
    average_sentence_length: float = Field(ge=0)
    long_sentence_count: int = Field(ge=0)
    heading_count: int = Field(ge=0)


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: GateId
    name: str = Field(min_length=1)
    passed: bool
    evidence: str
    reason: str
    required_fix: str


class SemanticEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gates: list[GateResult] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def has_each_gate_once(self) -> "SemanticEvaluation":
        gate_ids = [gate.gate_id for gate in self.gates]
        if set(gate_ids) != EXPECTED_GATE_IDS or len(set(gate_ids)) != len(gate_ids):
            raise ValueError("Semantic evaluation must contain each R1-R8 gate exactly once")
        return self

    @property
    def overall_pass(self) -> bool:
        """Compute the shipping decision in Python, never from LLM-provided data."""
        return all(gate.passed for gate in self.gates)


class FailurePacket(BaseModel):
    attempt: int = Field(ge=0)
    failed_gates: list[GateResult] = Field(min_length=1)


class LearnedGuardrail(BaseModel):
    """A bounded cross-run rule created from repeated failures."""

    guardrail_id: int | None = None
    gate_id: GateId
    rule: str = Field(min_length=1, max_length=500)
    source_run_count: int = Field(ge=2)
    active: bool = True


class AttemptRecord(BaseModel):
    attempt_number: int = Field(ge=0, le=2)
    lesson_path: str
    prompt_kind: Literal["initial", "revision"] = "initial"
    prompt_snapshot_path: str | None = None
    revision_feedback: FailurePacket | None = None
    static_evaluation: StaticEvaluation | None = None
    semantic_evaluation: SemanticEvaluation | None = None


class WorkflowEvent(BaseModel):
    """A persisted, presentation-safe progress event for one workflow run."""

    timestamp: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    status: Literal["started", "completed", "failed", "retry", "warning"]
    title: str = Field(min_length=1)
    detail: str = ""
    attempt: int | None = Field(default=None, ge=0, le=2)


class WorkflowState(BaseModel):
    """Explicit state contract to be used by the future LangGraph workflow."""

    topic: str = Field(min_length=1)
    learner_profile: LearnerProfile = Field(default_factory=LearnerProfile)
    run_id: str = Field(min_length=1)
    attempt_number: int = Field(default=0, ge=0, le=2)
    max_retries: int = Field(default=2, ge=0, le=2)
    final_status: Literal[
        "READY_TO_SHIP", "NEEDS_HUMAN_REVIEW", "RESEARCH_FAILED"
    ] | None = None
