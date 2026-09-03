"""Temporary local RAG facts for Stage 3 generation tests and live smoke checks."""

from __future__ import annotations

from models import CanonicalFact


def local_rag_facts() -> list[CanonicalFact]:
    return [
        CanonicalFact(
            fact_id="FACT_001",
            concept="definition",
            statement=(
                "Retrieval-augmented generation, or RAG, retrieves relevant external "
                "information and gives it to a language model while it prepares an answer."
            ),
            supported_by=["LOCAL_SRC_001"],
        ),
        CanonicalFact(
            fact_id="FACT_002",
            concept="workflow",
            statement=(
                "A basic RAG flow takes a question, finds relevant passages, adds those "
                "passages to the model context, and then generates an answer."
            ),
            supported_by=["LOCAL_SRC_001"],
        ),
        CanonicalFact(
            fact_id="FACT_003",
            concept="important distinction",
            statement=(
                "RAG does not retrain a model's weights for every user question; it adds "
                "retrieved information at answer time."
            ),
            supported_by=["LOCAL_SRC_001"],
        ),
        CanonicalFact(
            fact_id="FACT_004",
            concept="limitation",
            statement=(
                "A RAG answer can still be weak when retrieval finds irrelevant, outdated, "
                "or incomplete information."
            ),
            supported_by=["LOCAL_SRC_001"],
        ),
    ]
