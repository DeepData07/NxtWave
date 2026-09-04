from __future__ import annotations

from types import SimpleNamespace

from config import Settings
from lesson import generate_lesson, normalise_lesson_markdown, plan_lesson, save_lesson_artifact
from models import LearnerProfile, LessonPlan
from tests.rag_facts_fixture import local_rag_facts


def test_plan_lesson_uses_fast_model_and_parses_json() -> None:
    requests: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requests.append(request)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"title":"RAG basics","sections":["Problem","Flow"]}'
                        )
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings(
        together_api_key="test-key",
        tavily_api_key=None,
        fast_model="fast-model",
        generator_model="generator-model",
        evaluator_model="evaluator-model",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=50,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=60,
    )

    plan = plan_lesson(
        "Introduction to RAG",
        LearnerProfile(),
        local_rag_facts(),
        settings=settings,
        client=fake_client,
    )

    assert plan.title == "RAG basics"
    assert requests[0]["model"] == "fast-model"
    assert requests[0]["max_tokens"] == 50
    assert requests[0]["response_format"]["type"] == "json_schema"


def test_generation_prompt_contains_learner_and_fact_contract() -> None:
    requests: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requests.append(request)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="# Lesson\n\nBody"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings(
        together_api_key="test-key",
        tavily_api_key=None,
        fast_model="fast-model",
        generator_model="generator-model",
        evaluator_model="evaluator-model",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=50,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=60,
    )
    lesson = generate_lesson(
        "Introduction to RAG",
        LearnerProfile(),
        LessonPlan(title="RAG basics", sections=["Problem", "Flow"]),
        local_rag_facts(),
        settings=settings,
        client=fake_client,
    )

    user_prompt = requests[0]["messages"][-1]["content"]  # type: ignore[index]
    assert lesson == "# Lesson\n\nBody"
    assert requests[0]["model"] == "generator-model"
    assert "12th-grade graduate" in user_prompt
    assert "FACT_003" in user_prompt
    assert "## Step-by-step example" in user_prompt
    assert "standard LaTeX" in user_prompt


def test_generated_lesson_is_saved_as_an_attempt_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("config.RUNS_DIR", tmp_path / "runs")

    artifact_path = save_lesson_artifact("# Lesson", "stage3_test")

    assert artifact_path.name == "attempt_0.md"
    assert artifact_path.read_text(encoding="utf-8") == "# Lesson"


def test_exact_bare_heading_is_normalised_without_creating_missing_sections() -> None:
    lesson = "What is Cosine Similarity?\n\nA short introduction.\n\nQuick recap"

    normalised = normalise_lesson_markdown(lesson, "What is Cosine Similarity?")

    assert normalised.startswith("# What is Cosine Similarity?")
    assert "## Quick recap" in normalised
    assert "## Check your understanding" not in normalised


def test_legacy_math_and_tabular_output_are_made_portable() -> None:
    lesson = (
        "What is Cosine Similarity\n\n"
        "Value\tMeaning\n"
        "1\tSame direction\n\n"
        "[\n"
        "\\text{sim}(A,B)=\\frac{A\\cdot B}{|A|;|B|}\n"
        "]"
    )

    normalised = normalise_lesson_markdown(lesson, "What is Cosine Similarity")

    assert "| Value | Meaning |" in normalised
    assert "\\[" in normalised
    assert "\\lVert A \\rVert \\cdot \\lVert B \\rVert" in normalised
