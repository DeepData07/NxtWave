# NxtWave Lesson Quality Agent

A production-style, self-correcting lesson-generation workflow for zero-background learners. Given a topic, it researches grounded facts, creates a lesson, evaluates it against invariant quality gates, repairs only evidenced failures, and records recurring patterns as reusable guardrails for later runs.

The design prioritizes reliable, auditable quality over simply producing text that sounds plausible.

## What it does

1. Plans web research for the requested topic.
2. Discovers and curates authoritative sources with Tavily.
3. Builds a compact, cited knowledge pack from only the excerpts used as evidence.
4. Produces a structured beginner lesson with Together AI.
5. Checks deterministic rules and eight independent semantic quality gates.
6. Revises the artifact using concrete evaluator evidence, while keeping the rubric unchanged.
7. Stops when every gate passes or the revision budget is exhausted.
8. Stores an auditable run history, including prompts, scores, evidence, and lesson versions.
9. Learns capped cross-run guardrails from recurring failure patterns.

## Architecture

```text
Topic
  -> Research planner -> Tavily discovery -> Source curation -> Knowledge pack
  -> Lesson plan -> Initial generation
  -> Static checks + invariant semantic evaluator (R1-R8)
  -> pass: READY_TO_SHIP
  -> fail: targeted revision -> evaluate again
  -> exhausted: NEEDS_HUMAN_REVIEW

Persistent SQLite memory
  <- failed-gate patterns from completed runs
  -> most relevant learned guardrails for future initial prompts
```

The workflow is dynamic: it does not rely on a fixed topic list. The research plan, sources, facts, lesson plan, evaluator evidence, and repair feedback are derived from the topic entered for that run.

## Why this is RAG, not just a prompt

The generation prompt receives a per-run knowledge pack containing selected facts, source IDs, URLs, and relevant excerpts. The model is instructed to use that material as its factual grounding. The project deliberately does **not** add a vector database: each run uses a small, fresh research corpus, so direct context injection is simpler, cheaper, and easier to audit than embedding and retrieving a few documents from an index.

## Quick start

Requirements: Python 3.11+ and a Together AI API key. Tavily is recommended for live research.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with your own values:

```dotenv
TOGETHER_API_KEY=your_together_key
TAVILY_API_KEY=your_tavily_key
FAST_MODEL=
GENERATOR_MODEL=
EVALUATOR_MODEL=
MAX_RETRIES=2
```

Leaving the three model variables blank uses the safe defaults in `config.py`. Do not commit `.env`; it is ignored by Git.

Run all deterministic tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run a normal live workflow:

```powershell
.\.venv\Scripts\python.exe main.py --topic "Introduction to RAG"
```

Run an auditable correction demo. Fault injection affects attempt 0 only, so a clean revision can genuinely pass:

```powershell
.\.venv\Scripts\python.exe main.py --topic "Introduction to RAG" --fault rag_factual_error
```

Launch the visual interface:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Model and cost controls

The system uses separate roles so inexpensive models handle narrow tasks and the strongest available model is reserved for lesson generation.

| Role | Default model | Fallback |
| --- | --- | --- |
| Fast planning | `openai/gpt-oss-20b` | `Qwen/Qwen3.5-9B` |
| Lesson generation | `openai/gpt-oss-120b` | `Qwen/Qwen3.5-9B` |
| Semantic evaluation | `Qwen/Qwen3-235B-A22B-Instruct-2507-tput` | `Qwen/Qwen3.5-9B` |

`config.py` sets explicit request timeouts, retry bounds, and token budgets before any live call: fast work uses 400 tokens, research work 1200, generation 2200, and evaluation 1200. A non-authentication Together provider failure retries once with the configured fallback model. Authentication failures never retry against a fallback, because that would not help.

## Research and factual evidence

Research runs at most three focused searches, considers at most five results per search, and selects at most four sources. It prefers primary documentation, official providers, standards bodies, and credible academic material. The stored knowledge pack keeps the exact excerpts used for each fact, plus source IDs and URLs—not entire raw web pages. That makes a factual claim inspectable without creating a large, opaque data dump.

If live research cannot be completed, the run is marked `RESEARCH_FAILED`; it does not silently invent sources.

## Invariant quality gates

The evaluator criteria never change during retries. Only the lesson changes.

| Gate | What it checks |
| --- | --- |
| R1 | Accurate, grounded factual claims |
| R2 | Clear structure and prerequisite order |
| R3 | Suitable for a zero-background learner |
| R4 | Concrete examples and explanations |
| R5 | No unsupported or fabricated citations/claims |
| R6 | Useful final recap |
| R7 | Three learner-check questions |
| R8 | Safe, professional, readable presentation |

Shipping requires **both** `static_pass` and `semantic_evaluation.overall_pass`. A revision agent cannot declare its own work fixed; every new lesson is evaluated from scratch against the same R1-R8 rubric.

## Self-correction and self-evolution

There are three prompt layers:

1. **Stable base policy** — permanent guidance such as simple English, explained jargon, grounded facts, and prerequisite order.
2. **Current-run corrective feedback** — evaluator evidence for a specific failed gate, used only to repair the current lesson.
3. **Cross-run learned guardrails** — generalized rules created when the same failure pattern appears across separate runs.

For example, repeated R3 failures about advanced terminology appearing too early can become a reusable guardrail: start with a familiar problem and basic mental model before implementation vocabulary. Relevant guardrails are injected into later *initial* prompts; they do not weaken or modify the acceptance rubric.

The memory store requires a recurring pattern threshold of two, retains a bounded history, deduplicates rules, and injects at most the five most relevant active guardrails. This prevents prompt bloat while keeping the learning behaviour reviewable.

## Run artifacts and metrics

Each run is stored under `data/runs/<run_id>/` and includes:

```text
research_plan.json        source_manifest.json       canonical_facts.json
knowledge_pack.md         lesson_plan.json           attempt_0_prompt.txt
attempt_0_lesson.md       attempt_0_evaluation.json  attempt_1_...
run_summary.json          final_lesson.md            workflow_error.json (on provider failure)
```

The attempt evaluations show every gate’s pass/fail result, score, evidence, and recommended repair. `run_summary.json` makes progress across attempts visible, while saved prompts and lesson versions show exactly what changed. `final_lesson.md` is retained even for a review outcome so a human can inspect or submit the best produced content alongside its quality evidence.

`data/runs/` and the SQLite memory database are intentionally local and Git-ignored: they may contain API-derived content and should not be committed as source code.

## Streamlit UI

The UI lets a reviewer enter any topic, set a maximum revision count, optionally select a demonstration fault, run the workflow, and inspect saved runs. It displays:

- workflow status and the phase trace;
- curated sources and canonical facts;
- lesson versions, prompts, and per-attempt gate evidence;
- attempt-to-attempt metric changes;
- the final lesson and learned guardrails;
- the exact persisted provider/workflow error when a live call fails.

This makes a successful run and a bounded failure equally auditable.

## Repository layout

```text
app.py                 Streamlit reviewer interface
main.py                command-line workflow entry point
config.py              model, timeout, token, and safety budgets
research.py            dynamic research and knowledge-pack construction
lesson.py              lesson planning, generation, and revision prompts
evaluation.py          static validation and semantic gate evaluation
workflow.py            LangGraph orchestration and run persistence
memory.py              SQLite-backed cross-run guardrails
llm.py                 Together client and model fallback handling
models.py              typed data contracts
tests/                 deterministic and mocked workflow coverage
```

## Verification

The core suite uses deterministic and mocked tests, so CI does not consume credits or depend on a provider being available. Live LLM tests are optional smoke checks. The final suite contains 49 passing tests; the remaining LangGraph dependency warning is upstream deprecation noise and does not affect behaviour.

Useful checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m py_compile app.py main.py workflow.py
.\.venv\Scripts\python.exe main.py --help
```

## Failure behaviour

The revision loop is intentionally bounded: with `MAX_RETRIES=2`, the workflow makes attempt 0 plus up to two corrective revisions. It ends early when all hard gates pass. If gates still fail after that budget, the state becomes `NEEDS_HUMAN_REVIEW`; it does not loop forever or disguise a failure as success. Provider failures are persisted to `workflow_error.json` and surfaced in the UI with the exact exception message.

## Design trade-offs and limitations

- Live answers remain dependent on source availability and provider capacity; fallback models improve resilience but cannot guarantee a provider will always be available.
- Semantic evaluation is model-assisted, so the deterministic checks and saved evidence are important safeguards rather than claims of perfect automated judgment.
- Learned guardrails are intentionally conservative: they generalize repeated patterns, not one-off feedback.
- This is an educational quality system, not a substitute for expert review in high-stakes medical, legal, financial, or safety-critical domains.
- The system has a finite research budget and a finite revision budget by design, to control cost, latency, and runaway behaviour.

## Submission highlights

This project demonstrates dynamic topic grounding, independent quality evaluation, evidence-driven correction, bounded autonomous control, persistent cross-run learning, transparent artifacts, a usable reviewer UI, and deterministic verification. Its central claim is simple: quality criteria stay stable; the lesson improves because it is measured, diagnosed, and repaired against those same criteria.
