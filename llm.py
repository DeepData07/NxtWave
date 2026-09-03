"""Small, guarded Together AI client shared by later workflow stages."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from together import Together

from config import Settings, get_settings


class LLMConfigurationError(RuntimeError):
    """Raised when a required local LLM setting is absent."""


class LLMRequestError(RuntimeError):
    """Raised when Together cannot return a usable completion."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def create_client(settings: Settings | None = None) -> Together:
    """Create a no-retry client with the configured request timeout."""
    settings = settings or get_settings()
    if not settings.together_api_key:
        raise LLMConfigurationError(
            "TOGETHER_API_KEY is required locally before calling Together AI."
        )
    return Together(
        api_key=settings.together_api_key,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


def _completion_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise LLMRequestError(
            "Together returned a completion with no message content.", status_code=502
        ) from error
    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("Together returned an empty completion.", status_code=502)
    return content.strip()


def _request_completion(
    client: Together,
    *,
    model: str,
    messages: Sequence[dict[str, str]],
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Make one bounded request and translate provider errors into app errors."""
    request: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "max_tokens": max_tokens,
        "temperature": 0,
        "reasoning": {"enabled": False},
    }
    if response_format is not None:
        request["response_format"] = response_format

    try:
        response = client.chat.completions.create(**request)
    except Exception as error:  # Provider SDK exposes version-specific HTTP errors.
        raise LLMRequestError(
            f"Together request failed for model '{model}'.",
            status_code=getattr(error, "status_code", None),
        ) from error
    return _completion_text(response)


def _request_with_fallback(
    client: Together,
    *,
    model: str,
    fallback_model: str | None,
    messages: Sequence[dict[str, str]],
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Use one explicit fallback for an unavailable or server-failed primary model."""
    try:
        return _request_completion(
            client,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            response_format=response_format,
        )
    except LLMRequestError as error:
        if not fallback_model or error.status_code not in {404, 500, 502, 503, 504}:
            raise
        return _request_completion(
            client,
            model=fallback_model,
            messages=messages,
            max_tokens=max_tokens,
            response_format=response_format,
        )


def call_text_model(
    messages: Sequence[dict[str, str]],
    *,
    model: str | None = None,
    fallback_model: str | None = None,
    max_tokens: int | None = None,
    client: Together | None = None,
    settings: Settings | None = None,
) -> str:
    """Request bounded text using the configured fast model by default."""
    settings = settings or get_settings()
    return _request_with_fallback(
        client or create_client(settings),
        model=model or settings.fast_model,
        fallback_model=fallback_model or settings.fast_model_fallback,
        messages=messages,
        max_tokens=max_tokens or settings.fast_model_max_tokens,
    )


def call_json_model(
    messages: Sequence[dict[str, str]],
    *,
    model: str | None = None,
    fallback_model: str | None = None,
    max_tokens: int | None = None,
    client: Together | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Request and parse a JSON object; Pydantic validation belongs to callers."""
    settings = settings or get_settings()
    json_messages = [
        {
            "role": "system",
            "content": "Return only one valid JSON object. Do not use Markdown fences.",
        },
        *messages,
    ]
    text = _request_with_fallback(
        client or create_client(settings),
        model=model or settings.fast_model,
        fallback_model=fallback_model or settings.fast_model_fallback,
        messages=json_messages,
        max_tokens=max_tokens or settings.fast_model_max_tokens,
        response_format={"type": "json_object"},
    )
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMRequestError("Together returned malformed JSON.") from error
    if not isinstance(result, dict):
        raise LLMRequestError("Together JSON response must be an object.")
    return result


def verify_configured_models(
    client: Together | None = None, settings: Settings | None = None
) -> dict[str, bool]:
    """Check provider model-catalog membership without generating tokens."""
    settings = settings or get_settings()
    active_client = client or create_client(settings)
    try:
        catalog = active_client.models.list()
        models = catalog.data if hasattr(catalog, "data") else catalog
        available_models = {model.id for model in models}
    except Exception as error:
        raise LLMRequestError("Unable to retrieve the Together model catalog.") from error
    configured_models = {
        "FAST_MODEL": settings.fast_model,
        "GENERATOR_MODEL": settings.generator_model,
        "EVALUATOR_MODEL": settings.evaluator_model,
    }
    return {name: model in available_models for name, model in configured_models.items()}


def run_smoke_checks() -> None:
    """Run one tiny text request and one tiny structured-JSON request."""
    settings = get_settings()
    client = create_client(settings)
    model_status = verify_configured_models(client, settings)
    if not model_status["FAST_MODEL"]:
        raise LLMConfigurationError(
            "Configured Together FAST_MODEL is unavailable; set a supported model ID."
        )
    if not model_status["EVALUATOR_MODEL"]:
        fallback_status = {
            model.id for model in client.models.list()
        }
        if settings.evaluator_model_fallback not in fallback_status:
            raise LLMConfigurationError(
                "Configured EVALUATOR_MODEL and its fallback are both unavailable."
            )

    call_text_model(
        [{"role": "user", "content": "Reply with exactly: smoke-ok"}],
        max_tokens=12,
        client=client,
        settings=settings,
    )
    payload = call_json_model(
        [
            {
                "role": "user",
                "content": 'Return this JSON object exactly: {"status":"ok"}',
            }
        ],
        max_tokens=24,
        client=client,
        settings=settings,
    )
    if payload.get("status") != "ok":
        raise LLMRequestError("Together JSON smoke test returned an unexpected object.")
    print("Text smoke test: passed")
    print("Structured JSON smoke test: passed")
    unavailable = [name for name, available in model_status.items() if not available]
    if unavailable:
        print("Configured model fallback active for: " + ", ".join(unavailable))
    else:
        print("Configured models: all available")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Together AI client checks")
    parser.add_argument("--smoke-test", action="store_true")
    arguments = parser.parse_args()
    if not arguments.smoke_test:
        parser.error("Use --smoke-test to run the bounded Together AI checks.")
    run_smoke_checks()
