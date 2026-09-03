# Lesson Quality Agent

A staged take-home project for a self-evaluating, self-improving beginner-lesson generator. The system will use dynamic web-grounded retrieval, strict hard quality gates, bounded revision, and persistent guardrails across runs.

## Current status

**Stage 2 complete:** Together SDK v2 client, configuration, error handling, and smoke checks are implemented.

## Planned architecture

```text
Topic -> research -> source curation -> knowledge pack -> lesson generation
      -> deterministic + semantic evaluation -> ship or bounded revision
      -> run artifacts and persistent learning memory
```

The final system will use direct injection of a small, auditable evidence pack (2–4 authoritative sources) rather than a vector database. At curriculum scale, the research layer can be replaced by hybrid vector + keyword retrieval without changing the workflow contract.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pytest -q
```

Copy `.env.example` to `.env` only when a later stage explicitly requires credentials. Keep all values local; `.env` is ignored by Git.

## Repository layout

```text
config.py          Local settings and run-directory helper
models.py          Shared Pydantic domain contracts
evaluation.py      Deterministic lesson checks and diagnostics
llm.py             Bounded Together client and smoke-test command
data/runs/         Per-run output artifacts (created on demand)
tests/             Fast, credential-free unit tests
```

Later stages will add the workflow, semantic evaluation, research, persistence, CLI, and Streamlit UI incrementally.

## Together smoke test

After adding `TOGETHER_API_KEY` to your local `.env`, run:

```powershell
python -m llm --smoke-test
```

It makes one tiny text request (12 output tokens maximum) and one tiny JSON request
(24 output tokens maximum). The project uses Together SDK v2. The configured
`openai/gpt-oss-20b` primary has the verified `Qwen/Qwen3.5-9B` fallback, and the
original evaluator model ID has the verified
`Qwen/Qwen3-235B-A22B-Instruct-2507-FP8` fallback. A fallback is used at most once
when Together reports a missing model, a 5xx provider error, or an empty completion.

## Current deterministic checks

The evaluator rejects an empty or out-of-range lesson, missing required headings,
a missing example or recap section, fewer than three learner-check questions, and
an invalid retry count. It also reports word count, heading count, average sentence
length, and the count of sentences longer than 30 words. These diagnostics inform
later semantic judgment; they do not by themselves decide beginner accessibility.

## Confirmed implementation refinements

The following decisions apply to later stages and are intentionally recorded before implementation:

- A lesson ships only when both deterministic checks pass and all eight semantic gates pass.
- `config.py` will hold explicit per-role token budgets and request timeouts before any live API call.
- Stage 2 will verify the configured Together model IDs and support environment-configured fallback model IDs.
- Research artifacts will preserve source IDs, URLs, and only the excerpts used to support canonical facts.
- Demo fault injection applies only to the first generated attempt; revised attempts remain clean.
- Persistent memory will load a bounded, relevance-ranked set of active guardrails (default maximum: five).
- Automated tests remain deterministic or mocked; paid, live-provider checks are manual integration tests.
