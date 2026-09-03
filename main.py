"""Command-line entry point for one auditable, dynamic lesson-quality run."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Callable

from workflow import DemoFault, WorkflowData, run_dynamic_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and evaluate a grounded beginner lesson.")
    parser.add_argument("--topic", required=True, help="Topic to teach, for example 'Introduction to RAG'.")
    parser.add_argument(
        "--fault",
        choices=["none", "rag_factual_error", "overly_technical_language", "remove_example_section"],
        default="none",
        help="Optional demo-only fault, applied only to attempt 0.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional artifact directory name; defaults to a timestamped CLI run ID.",
    )
    return parser


def main(
    arguments: list[str] | None = None,
    workflow_runner: Callable[..., WorkflowData] | None = None,
) -> int:
    args = build_parser().parse_args(arguments)
    topic = args.topic.strip()
    if not topic:
        raise SystemExit("--topic must not be empty")
    run_id = args.run_id or datetime.now().strftime("cli_%Y%m%d_%H%M%S")
    print(f"Starting grounded lesson workflow for: {topic}")
    state = (workflow_runner or run_dynamic_workflow)(
        topic, run_id=run_id, demo_fault=args.fault  # type: ignore[arg-type]
    )
    status = state["final_status"]
    print(f"Final status: {status}")
    print(f"Artifacts: data/runs/{run_id}")
    return 0 if status == "READY_TO_SHIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
