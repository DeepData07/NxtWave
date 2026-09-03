from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from config import Settings
from models import SearchCandidate
from research import (
    ResearchError,
    _select_evidence_excerpt,
    dedupe_candidates,
    normalise_url,
    run_research,
)


def settings() -> Settings:
    return Settings(
        together_api_key="test-key",
        tavily_api_key="test-tavily-key",
        fast_model="fast-model",
        generator_model="generator-model",
        evaluator_model="evaluator-model",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=100,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=100,
    )


class FakeLLMClient:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = iter(payloads)
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request: object) -> object:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(self.payloads))))]
        )


class FakeTavilyClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, **request: object) -> dict[str, object]:
        self.queries.append(str(request["query"]))
        if len(self.queries) == 1:
            return {
                "results": [
                    {
                        "title": "Primary paper",
                        "url": "https://example.edu/paper?utm_source=test",
                        "raw_content": "RAG retrieves relevant documents before answering.",
                    },
                    {
                        "title": "Duplicate paper",
                        "url": "https://example.edu/paper",
                        "raw_content": "Duplicate source content.",
                    },
                ]
            }
        return {
            "results": [
                {
                    "title": "Official documentation",
                    "url": "https://docs.example.org/rag",
                    "raw_content": "Retrieved context can improve answers when relevant.",
                }
            ]
        }


def test_normalise_url_removes_tracking_and_fragments() -> None:
    assert normalise_url("HTTPS://Example.com/path/?utm_source=x&a=1#section") == (
        "https://example.com/path?a=1"
    )


def test_dedupe_candidates_preserves_first_real_url() -> None:
    candidates = [
        SearchCandidate(
            candidate_id="CAND_001",
            title="First",
            url="https://example.com/page?utm_source=x",
        ),
        SearchCandidate(
            candidate_id="CAND_002",
            title="Second",
            url="https://example.com/page",
        ),
    ]

    deduped = dedupe_candidates(candidates)

    assert len(deduped) == 1
    assert deduped[0].title == "First"
    assert deduped[0].candidate_id == "CAND_001"


def test_evidence_excerpt_is_real_bounded_source_text() -> None:
    source = "Intro text. RAG retrieves relevant documents before generating an answer. Closing text."

    excerpt = _select_evidence_excerpt(
        "RAG retrieves relevant documents before generating an answer.", source
    )

    assert excerpt == "RAG retrieves relevant documents before generating an answer."
    assert excerpt in source


def test_dynamic_research_preserves_tavily_provenance_and_artifacts(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    llm = FakeLLMClient(
        {
            "canonical_topic": "Retrieval-Augmented Generation",
            "learning_scope": ["definition", "workflow", "limitations"],
            "search_queries": ["RAG paper", "RAG documentation"],
        },
        {
            "selections": [
                {
                    "candidate_id": "CAND_001",
                    "authority_type": "university",
                    "selection_reason": "Primary research source.",
                },
                {
                    "candidate_id": "CAND_002",
                    "authority_type": "official documentation",
                    "selection_reason": "Relevant corroborating technical documentation.",
                },
            ]
        },
        {
            "facts": [
                {
                    "fact_id": "MODEL_ID_IGNORED",
                    "concept": "definition",
                    "statement": "RAG retrieves relevant documents before answering.",
                    "supported_by": ["SRC_001"],
                    "status": "supported",
                    "evidence": [
                        {
                            "source_id": "SRC_001",
                            "excerpt": "RAG retrieves relevant documents before answering.",
                        }
                    ],
                }
            ]
        },
    )
    tavily = FakeTavilyClient()

    result = run_research(
        "Introduction to RAG",
        run_id="research_test",
        settings=settings(),
        llm_client=llm,
        tavily_client=tavily,  # type: ignore[arg-type]
    )

    run_directory = tmp_path / "runs" / "research_test"
    manifest = json.loads((run_directory / "source_manifest.json").read_text(encoding="utf-8"))
    facts = json.loads((run_directory / "canonical_facts.json").read_text(encoding="utf-8"))
    assert tavily.queries == ["RAG paper", "RAG documentation"]
    assert len(result.candidates) == 2
    assert [source.source_id for source in result.selected_sources] == ["SRC_001", "SRC_002"]
    assert manifest[0]["url"] == "https://example.edu/paper?utm_source=test"
    assert result.canonical_facts[0].fact_id == "FACT_001"
    assert facts[0]["evidence"] == [
        {"source_id": "SRC_001", "excerpt": "RAG retrieves relevant documents before answering."}
    ]
    assert (run_directory / "research_plan.json").is_file()
    assert (run_directory / "canonical_facts.json").is_file()
    assert (run_directory / "knowledge_pack.md").is_file()


def test_research_rejects_fact_that_references_unselected_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")
    llm = FakeLLMClient(
        {
            "canonical_topic": "Topic",
            "learning_scope": ["definition"],
            "search_queries": ["topic one", "topic two"],
        },
        {
            "selections": [
                {
                    "candidate_id": "CAND_001",
                    "authority_type": "university",
                    "selection_reason": "Selected source.",
                }
            ]
        },
        {
            "facts": [
                {
                    "fact_id": "FACT_999",
                    "concept": "definition",
                    "statement": "Unsupported provenance.",
                    "supported_by": ["SRC_999"],
                    "status": "supported",
                    "evidence": [
                        {"source_id": "SRC_999", "excerpt": "Unsupported provenance."}
                    ],
                }
            ]
        },
    )

    with pytest.raises(ResearchError, match="outside the selected manifest"):
        run_research(
            "Topic",
            run_id="invalid_provenance",
            settings=settings(),
            llm_client=llm,
            tavily_client=FakeTavilyClient(),  # type: ignore[arg-type]
        )
