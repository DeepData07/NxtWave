"""Dynamic Tavily research and small, provenance-preserving knowledge packs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re

from pydantic import ValidationError
from tavily import TavilyClient

from config import Settings, ensure_run_directory, get_settings
from llm import LLMConfigurationError, LLMRequestError, call_json_model
from models import (
    CanonicalFact,
    FactEvidence,
    LearnerProfile,
    ResearchPlan,
    SearchCandidate,
    SelectedSource,
    SourceCuration,
)
from prompts import (
    build_fact_extraction_messages,
    build_research_plan_messages,
    build_source_curation_messages,
)


MAX_QUERIES = 3
MAX_RESULTS_PER_QUERY = 5
MAX_SELECTED_SOURCES = 4


class ResearchError(RuntimeError):
    """Raised when dynamic research cannot produce an adequate knowledge contract."""


@dataclass(frozen=True)
class ResearchResult:
    plan: ResearchPlan
    candidates: list[SearchCandidate]
    selected_sources: list[SelectedSource]
    canonical_facts: list[CanonicalFact]
    knowledge_pack: str


def _source_curation_schema() -> dict[str, Any]:
    choice = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "authority_type": {"type": "string"},
            "selection_reason": {"type": "string"},
        },
        "required": ["candidate_id", "authority_type", "selection_reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "selections": {"type": "array", "minItems": 1, "maxItems": 4, "items": choice}
        },
        "required": ["selections"],
        "additionalProperties": False,
    }


def _fact_extraction_schema() -> dict[str, Any]:
    fact = {
        "type": "object",
        "properties": {
            "fact_id": {"type": "string"},
            "concept": {"type": "string", "maxLength": 100},
            "statement": {"type": "string", "maxLength": 400},
            "supported_by": {
                "type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}
            },
            "status": {"type": "string", "enum": ["supported", "single_source", "conflicting"]},
        },
        "required": ["fact_id", "concept", "statement", "supported_by", "status"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "minItems": 1, "maxItems": 10, "items": fact}
        },
        "required": ["facts"],
        "additionalProperties": False,
    }


def _call_fast_json(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int,
    settings: Settings,
    client: object | None,
) -> dict[str, Any]:
    """Use the configured fast model, then one fallback only for malformed JSON."""
    try:
        return call_json_model(
            messages,
            model=settings.fast_model,
            fallback_model=settings.fast_model_fallback,
            max_tokens=max_tokens,
            json_schema=schema,
            schema_name=schema_name,
            client=client,  # type: ignore[arg-type]
            settings=settings,
        )
    except LLMRequestError as error:
        if error.status_code is not None or not settings.fast_model_fallback:
            raise
        return call_json_model(
            messages,
            model=settings.fast_model_fallback,
            fallback_model=None,
            max_tokens=max_tokens,
            json_schema=schema,
            schema_name=schema_name,
            client=client,  # type: ignore[arg-type]
            settings=settings,
        )
def create_search_plan(
    topic: str,
    learner: LearnerProfile,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> ResearchPlan:
    """Use the fast model to create a bounded, structured search plan."""
    settings = settings or get_settings()
    try:
        payload = _call_fast_json(
            build_research_plan_messages(topic, learner),
            schema=ResearchPlan.model_json_schema(),
            schema_name="research_plan",
            max_tokens=settings.fast_model_max_tokens,
            settings=settings,
            client=client,  # type: ignore[arg-type]
        )
        return ResearchPlan.model_validate(payload)
    except (LLMRequestError, ValidationError) as error:
        raise ResearchError("Unable to create a valid research plan.") from error


def normalise_url(url: str) -> str:
    """Remove fragments and tracking query parameters for deterministic deduplication."""
    parsed = urlsplit(url)
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        )
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))


def run_tavily_search(
    plan: ResearchPlan, *, tavily_client: TavilyClient | None = None, settings: Settings | None = None
) -> list[SearchCandidate]:
    """Run at most three Tavily queries and retain bounded source excerpts."""
    settings = settings or get_settings()
    if not settings.tavily_api_key and tavily_client is None:
        raise LLMConfigurationError("TAVILY_API_KEY is required locally before web research.")
    client = tavily_client or TavilyClient(api_key=settings.tavily_api_key)
    raw_candidates: list[SearchCandidate] = []
    try:
        for query in plan.search_queries[:MAX_QUERIES]:
            response = client.search(
                query=query,
                search_depth="basic",
                max_results=MAX_RESULTS_PER_QUERY,
                include_raw_content="markdown",
            )
            for item in response.get("results", []):
                url = item.get("url")
                title = item.get("title")
                if not url or not title:
                    continue
                raw_candidates.append(
                    SearchCandidate(
                        candidate_id=f"CAND_{len(raw_candidates) + 1:03d}",
                        title=title,
                        url=url,
                        content=(item.get("raw_content") or item.get("content") or "")[:12000],
                    )
                )
    except Exception as error:
        raise ResearchError("Tavily source discovery failed.") from error
    candidates = dedupe_candidates(raw_candidates)
    if not candidates:
        raise ResearchError("Tavily returned no usable source candidates.")
    return candidates


def dedupe_candidates(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    """Keep the first real Tavily result for each normalized URL and renumber candidates."""
    unique: list[SearchCandidate] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        normalized = normalise_url(str(candidate.url))
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        unique.append(
            candidate.model_copy(update={"candidate_id": f"CAND_{len(unique) + 1:03d}"})
        )
    return unique[: MAX_QUERIES * MAX_RESULTS_PER_QUERY]


def curate_sources(
    topic: str,
    candidates: list[SearchCandidate],
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> list[SelectedSource]:
    """Select 1-4 real Tavily candidates without allowing model-invented URLs."""
    settings = settings or get_settings()
    try:
        payload = _call_fast_json(
            build_source_curation_messages(topic, candidates),
            schema=_source_curation_schema(),
            schema_name="source_curation",
            max_tokens=settings.fast_model_max_tokens,
            settings=settings,
            client=client,  # type: ignore[arg-type]
        )
        curation = SourceCuration.model_validate(payload)
    except (LLMRequestError, ValidationError) as error:
        raise ResearchError("Unable to curate sources from Tavily candidates.") from error

    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected: list[SelectedSource] = []
    for choice in curation.selections:
        candidate = candidates_by_id.get(choice.candidate_id)
        if candidate is None or any(source.url == candidate.url for source in selected):
            continue
        selected.append(
            SelectedSource(
                **candidate.model_dump(),
                source_id=f"SRC_{len(selected) + 1:03d}",
                domain=candidate.url.host or "unknown",
                authority_type=choice.authority_type,
                selection_reason=choice.selection_reason,
            )
        )
    if not selected:
        raise ResearchError("Source curator selected no valid Tavily candidates.")
    return selected[:MAX_SELECTED_SOURCES]


def build_canonical_facts(
    topic: str,
    learning_scope: list[str],
    selected_sources: list[SelectedSource],
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> list[CanonicalFact]:
    """Extract facts whose provenance is limited to selected real sources."""
    settings = settings or get_settings()
    try:
        payload = _call_fast_json(
            build_fact_extraction_messages(topic, learning_scope, selected_sources),
            schema=_fact_extraction_schema(),
            schema_name="canonical_facts",
            max_tokens=settings.research_fact_max_tokens,
            settings=settings,
            client=client,  # type: ignore[arg-type]
        )
    except LLMRequestError as error:
        raise ResearchError("Unable to extract canonical facts from selected sources.") from error

    selected_ids = {source.source_id for source in selected_sources}
    source_content_by_id = {source.source_id: source.content for source in selected_sources}
    facts: list[CanonicalFact] = []
    for item in payload.get("facts", []):
        try:
            supported_by = item["supported_by"]
            if not set(supported_by).issubset(selected_ids):
                raise ResearchError("Fact extraction referenced a source outside the selected manifest.")
            source_id = supported_by[0]
            evidence = [
                FactEvidence(
                    source_id=source_id,
                    excerpt=_select_evidence_excerpt(item["statement"], source_content_by_id[source_id]),
                )
            ]
            facts.append(
                CanonicalFact(
                    fact_id=f"FACT_{len(facts) + 1:03d}",
                    concept=item["concept"],
                    statement=item["statement"],
                    supported_by=supported_by,
                    status=item["status"],
                    evidence=evidence,
                )
            )
        except (KeyError, ValidationError, TypeError) as error:
            raise ResearchError("Fact extraction returned an invalid canonical fact.") from error
    if not facts:
        raise ResearchError("Source curation completed but no canonical facts were extracted.")
    return facts[:10]


def _select_evidence_excerpt(statement: str, source_content: str) -> str:
    """Select a bounded real source sentence with the strongest lexical support."""
    normalized_content = re.sub(r"\s+", " ", source_content).strip()
    candidates = re.split(r"(?<=[.!?])\s+", normalized_content)
    terms = set(re.findall(r"[a-z0-9]{3,}", statement.lower()))

    def score(candidate: str) -> int:
        return len(terms.intersection(re.findall(r"[a-z0-9]{3,}", candidate.lower())))

    excerpt = max(candidates, key=score, default=normalized_content)
    return (excerpt or normalized_content)[:300]


def render_knowledge_pack(
    topic: str, plan: ResearchPlan, sources: list[SelectedSource], facts: list[CanonicalFact]
) -> str:
    """Create a concise human-readable grounding contract for inspection."""
    lines = [f"# Knowledge Pack: {topic}", "", "## Learning scope"]
    lines.extend(f"- {item}" for item in plan.learning_scope)
    lines.extend(["", "## Selected sources"])
    for source in sources:
        lines.extend(
            [
                f"- **{source.source_id} — {source.title}**",
                f"  - URL: {source.url}",
                f"  - Authority: {source.authority_type}",
                f"  - Why selected: {source.selection_reason}",
            ]
        )
    lines.extend(["", "## Canonical facts"])
    for fact in facts:
        lines.append(
            f"- **{fact.fact_id}** ({fact.concept}; {fact.status}; "
            f"sources: {', '.join(fact.supported_by)}): {fact.statement}"
        )
        for snippet in fact.evidence:
            lines.append(f"  - Evidence from {snippet.source_id}: {snippet.excerpt}")
    return "\n".join(lines) + "\n"


def save_research_artifacts(result: ResearchResult, run_id: str) -> Path:
    """Persist all provenance artifacts required for one dynamic research run."""
    run_directory = ensure_run_directory(run_id)
    (run_directory / "research_plan.json").write_text(
        result.plan.model_dump_json(indent=2), encoding="utf-8"
    )
    manifest = [
        {
            "source_id": source.source_id,
            "title": source.title,
            "url": str(source.url),
            "domain": source.domain,
            "authority_type": source.authority_type,
            "why_selected": source.selection_reason,
        }
        for source in result.selected_sources
    ]
    (run_directory / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (run_directory / "canonical_facts.json").write_text(
        json.dumps([fact.model_dump(mode="json") for fact in result.canonical_facts], indent=2),
        encoding="utf-8",
    )
    (run_directory / "knowledge_pack.md").write_text(result.knowledge_pack, encoding="utf-8")
    return run_directory


def run_research(
    topic: str,
    *,
    learner: LearnerProfile | None = None,
    run_id: str,
    settings: Settings | None = None,
    llm_client: object | None = None,
    tavily_client: TavilyClient | None = None,
) -> ResearchResult:
    """Build and save a dynamic, auditable knowledge pack for an arbitrary topic."""
    learner = learner or LearnerProfile()
    plan = create_search_plan(topic, learner, settings=settings, client=llm_client)
    candidates = run_tavily_search(plan, tavily_client=tavily_client, settings=settings)
    selected_sources = curate_sources(topic, candidates, settings=settings, client=llm_client)
    facts = build_canonical_facts(
        topic,
        plan.learning_scope,
        selected_sources,
        settings=settings,
        client=llm_client,
    )
    result = ResearchResult(
        plan=plan,
        candidates=candidates,
        selected_sources=selected_sources,
        canonical_facts=facts,
        knowledge_pack=render_knowledge_pack(topic, plan, selected_sources, facts),
    )
    save_research_artifacts(result, run_id)
    return result
