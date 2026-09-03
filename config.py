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
    max_retries: int


def get_settings() -> Settings:
    """Load environment overrides while keeping model defaults in one place."""
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        together_api_key=os.getenv("TOGETHER_API_KEY") or None,
        tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
        fast_model=os.getenv("FAST_MODEL", "openai/gpt-oss-20b"),
        generator_model=os.getenv("GENERATOR_MODEL", "openai/gpt-oss-120b"),
        evaluator_model=os.getenv(
            "EVALUATOR_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507-tput"
        ),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
    )


def ensure_run_directory(run_id: str) -> Path:
    """Create and return the artifact directory for one workflow run."""
    if not run_id or any(character in run_id for character in "\\/:"):
        raise ValueError("run_id must be a non-empty filename-safe identifier")
    run_directory = RUNS_DIR / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    return run_directory
