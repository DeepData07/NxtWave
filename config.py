"""Project configuration with safe local defaults for the staged build."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Secrets are read locally and never logged."""

    together_api_key: str | None
    tavily_api_key: str | None
    fast_model: str
    generator_model: str
    evaluator_model: str
    fast_model_fallback: str | None
    generator_model_fallback: str | None
    evaluator_model_fallback: str | None
    max_retries: int
    request_timeout_seconds: float
    fast_model_max_tokens: int
    generator_model_max_tokens: int
    evaluator_model_max_tokens: int
    research_fact_max_tokens: int = 1200


def get_settings() -> Settings:
    """Load environment overrides while keeping model defaults in one place."""
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        together_api_key=os.getenv("TOGETHER_API_KEY") or None,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
        fast_model=os.getenv("FAST_MODEL") or "openai/gpt-oss-20b",
        generator_model=os.getenv("GENERATOR_MODEL") or "openai/gpt-oss-120b",
        evaluator_model=os.getenv("EVALUATOR_MODEL")
        or "Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
        fast_model_fallback=os.getenv("FAST_MODEL_FALLBACK") or "Qwen/Qwen3.5-9B",
        generator_model_fallback=os.getenv("GENERATOR_MODEL_FALLBACK")
        or "Qwen/Qwen3.5-9B",
        evaluator_model_fallback=os.getenv("EVALUATOR_MODEL_FALLBACK")
        or "Qwen/Qwen3.5-9B",
        max_retries=int(os.getenv("MAX_RETRIES") or "2"),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS") or "30"),
        fast_model_max_tokens=int(os.getenv("FAST_MODEL_MAX_TOKENS") or "400"),
        generator_model_max_tokens=int(
            os.getenv("GENERATOR_MODEL_MAX_TOKENS") or "2200"
        ),
        evaluator_model_max_tokens=int(
            os.getenv("EVALUATOR_MODEL_MAX_TOKENS") or "1200"
        ),
        research_fact_max_tokens=int(os.getenv("RESEARCH_FACT_MAX_TOKENS") or "1200"),
    )


def ensure_run_directory(run_id: str) -> Path:
    """Create and return the artifact directory for one workflow run."""
    if not run_id or any(character in run_id for character in "\\/:"):
        raise ValueError("run_id must be a non-empty filename-safe identifier")
    run_directory = RUNS_DIR / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    return run_directory
