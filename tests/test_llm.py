from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import Settings
from llm import (
    LLMConfigurationError,
    LLMRequestError,
    call_json_model,
    call_text_model,
    create_client,
    verify_configured_models,
)


def test_create_client_requires_a_local_key() -> None:
    settings = Settings(
        together_api_key=None,
        tavily_api_key=None,
        fast_model="fast",
        generator_model="generator",
        evaluator_model="evaluator",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=40,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=60,
    )

    with pytest.raises(LLMConfigurationError, match="TOGETHER_API_KEY"):
        create_client(settings)


def test_text_call_uses_configured_limit_with_a_mock_client() -> None:
    requests: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requests.append(request)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="smoke-ok"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = call_text_model(
        [{"role": "user", "content": "hello"}],
        model="test-model",
        max_tokens=12,
        client=fake_client,  # type: ignore[arg-type]
    )

    assert result == "smoke-ok"
    assert requests[0]["model"] == "test-model"
    assert requests[0]["max_tokens"] == 12


def test_json_call_rejects_non_object_response() -> None:
    class FakeCompletions:
        def create(self, **request: object) -> object:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="[1, 2]"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    with pytest.raises(LLMRequestError, match="must be an object"):
        call_json_model(
            [{"role": "user", "content": "hello"}],
            client=fake_client,  # type: ignore[arg-type]
        )


def test_json_call_passes_an_optional_json_schema() -> None:
    requests: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requests.append(request)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"status":"ok"}'))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = call_json_model(
        [{"role": "user", "content": "hello"}],
        json_schema={"type": "object"},
        schema_name="smoke_schema",
        client=fake_client,  # type: ignore[arg-type]
    )

    assert result == {"status": "ok"}
    assert requests[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "smoke_schema", "schema": {"type": "object"}},
    }


def test_model_catalog_accepts_v2_list_response() -> None:
    settings = Settings(
        together_api_key="local-test-key",
        tavily_api_key=None,
        fast_model="fast",
        generator_model="generator",
        evaluator_model="evaluator",
        fast_model_fallback=None,
        generator_model_fallback=None,
        evaluator_model_fallback=None,
        max_retries=2,
        request_timeout_seconds=30,
        fast_model_max_tokens=40,
        generator_model_max_tokens=100,
        evaluator_model_max_tokens=60,
    )
    fake_client = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: [
                SimpleNamespace(id="fast"),
                SimpleNamespace(id="generator"),
                SimpleNamespace(id="evaluator"),
            ]
        )
    )

    assert verify_configured_models(fake_client, settings) == {
        "FAST_MODEL": True,
        "GENERATOR_MODEL": True,
        "EVALUATOR_MODEL": True,
    }


def test_text_call_retries_one_recoverable_model_error_with_its_fallback() -> None:
    requested_models: list[str] = []

    class MissingModelError(Exception):
        status_code = 400
        body = {"error": {"code": "model_not_available"}}

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requested_models.append(str(request["model"]))
            if request["model"] == "retired-model":
                raise MissingModelError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fallback answer"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = call_text_model(
        [{"role": "user", "content": "hello"}],
        model="retired-model",
        fallback_model="supported-model",
        client=fake_client,  # type: ignore[arg-type]
    )

    assert result == "fallback answer"
    assert requested_models == ["retired-model", "supported-model"]


def test_text_call_uses_fallback_when_provider_omits_a_status_code() -> None:
    requested_models: list[str] = []

    class TemporaryProviderError(Exception):
        pass

    class FakeCompletions:
        def create(self, **request: object) -> object:
            requested_models.append(str(request["model"]))
            if request["model"] == "primary-model":
                raise TemporaryProviderError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fallback answer"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    result = call_text_model(
        [{"role": "user", "content": "hello"}],
        model="primary-model",
        fallback_model="fallback-model",
        client=fake_client,  # type: ignore[arg-type]
    )

    assert result == "fallback answer"
    assert requested_models == ["primary-model", "fallback-model"]
