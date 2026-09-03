# Lesson Quality Agent

A staged take-home project for a self-evaluating, self-improving beginner-lesson generator. The system will use dynamic web-grounded retrieval, strict hard quality gates, bounded revision, and persistent guardrails across runs.

## Current status

**Stage 8 complete:** dynamic grounding, a bounded correction loop, and SQLite-backed
cross-run guardrails are implemented.

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
app.py              Thin Streamlit workflow/demo surface
models.py          Shared Pydantic domain contracts
evaluation.py      Deterministic lesson checks and diagnostics
llm.py             Bounded Together client and smoke-test command
prompts.py         Visible prompts for planning and first-attempt generation
lesson.py          Grounded lesson planning, generation, and artifact saving
memory.py          SQLite failure history and learned-guardrail promotion
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
original evaluator model ID has the verified `Qwen/Qwen3.5-9B` fallback. A fallback is used at most once
when Together reports a missing model (including its `model_not_available` provider
code), a 5xx provider error, or an empty completion.

## Stage 3 local-grounding validation

Before Tavily is introduced, Stage 3 uses a temporary local RAG fact fixture. The
planner receives those facts as JSON context, the generator receives the same fact
contract and learner profile, and the lesson is saved as `attempt_0.md` in a run
directory. Live generation is validated separately from the mocked unit tests.

## Prompt architecture and improvement audit

The system keeps three prompt layers distinct:

1. **Stable base policy** — consistent beginner-teaching, grounding, jargon, and flow rules.
2. **Current-run corrective feedback** — later revision prompts receive only the failed gates, their evidence, and their required fixes.
3. **Cross-run learned guardrails** — Stage 8 will promote recurring failures into bounded rules injected into future *initial* prompts.

The eight-gate rubric is invariant across attempts. A revision is never trusted because
it claims to be better: the complete replacement lesson is evaluated again against the
same learner profile, facts, and R1–R8 rubric.

Stages 5 and 8 will save an auditable record for each attempt: lesson version, prompt
snapshot, static metrics (word count, average sentence length, long-sentence count,
and heading count), gate outcomes, evaluator evidence, failure packet, and revision
feedback. This lets the UI and Loom walkthrough show precisely what changed and which
metrics or gates improved without moving the acceptance criteria.

## Semantic evaluator

`run_semantic_evaluation()` evaluates the complete lesson independently against R1–R8
using the same learner profile and canonical facts as the generator. It requires a
provider-friendly JSON Schema plus Pydantic validation with every gate exactly once,
retries malformed formatting once without using a lesson revision, and creates a
failure packet containing only failed gates.

## Attempt history and bounded correction

Stage 5 records an audit bundle for every lesson attempt: `prompt_<n>.md`,
`attempt_<n>.md`, `static_evaluation_<n>.json`, `evaluation_<n>.json`, and, when
needed, `failure_packet_<n>.json`. The final `run_summary.json` contains a comparison
of all static metrics and gate outcomes; `rejection_log.json` records exactly why an
attempt was rejected.

The LangGraph workflow applies demo faults only to attempt 0. Every revised lesson is
then re-evaluated with the same deterministic checks, learner profile, canonical facts,
and stable R1–R8 rubric. It stops after the initial generation plus at most two revisions:
`READY_TO_SHIP` when every hard requirement passes, otherwise `NEEDS_HUMAN_REVIEW`.

## Dynamic source grounding

Stage 6 replaces the temporary fixture only for research validation. A fast model plans
two or three queries; Tavily retrieves at most five results per query; a curator selects
at most four real candidates; and fact extraction records only selected source IDs plus
the short source excerpts used to support each fact. Fact
extraction has its own bounded 1,200-token budget and returns at most four concise facts;
planning and curation use the smaller
fast-model budget.
Every run saves `research_plan.json`, `source_manifest.json`, `canonical_facts.json`,
and `knowledge_pack.md`. URLs are copied only from Tavily results—models never invent
them. Retrieved pages are treated as untrusted evidence, never instructions.

## End-to-end dynamic workflow

`run_dynamic_workflow()` is the live entry point. It writes research artifacts and
lesson-attempt artifacts into the same `data/runs/<run_id>/` directory, then ships only
when both deterministic checks and `semantic_evaluation.overall_pass` succeed. If
grounding fails, it writes a `RESEARCH_FAILED` run summary and never generates an
ungrounded lesson. The existing `run_workflow()` entry point remains available for free,
fixture-based tests.

```python
from workflow import run_dynamic_workflow

state = run_dynamic_workflow("Introduction to RAG", run_id="rag_normal")
print(state["final_status"])
```

For the bounded factual-error demo, use `demo_fault="rag_factual_error"`. The fault is
applied only to attempt 0; revisions are clean and are evaluated again from scratch.

## Streamlit demo

Run the visual demo locally with:

```powershell
streamlit run app.py
```

The UI can launch a new dynamic workflow or inspect a saved artifact bundle. It displays
sources, per-attempt metrics and gate comparison, evaluator evidence/fixes, rejection
history, prompt snapshots, loaded/prompted memory guardrails, and the final lesson only
when it has passed every hard requirement. It never displays API keys.

## Persistent self-evolving guardrails

SQLite memory at `data/lesson_memory.db` records semantic gate failures once per
`run_id` and gate. A repeated failure inside one retry loop cannot inflate the count.
After the default threshold of two distinct runs, one bounded fast-model distillation
creates a reusable rule for that gate. Demo-fault runs never update memory, preventing
deliberate defects from teaching the system the wrong lesson.

Before every dynamic run, the workflow loads at most five active guardrails (ranked by
the number of distinct supporting runs) and injects their rules into the lesson planner
and initial generator. The invariant R1–R8 rubric never changes. Each run saves
`loaded_guardrails.json` and `memory_update.json` alongside its attempts, sources, and
evaluations, making the difference between self-correction and cross-run evolution
auditable.

If Together fails during a later lesson generation or evaluation request, the workflow
preserves completed attempts and writes `workflow_error.json`. The run ends as
`NEEDS_HUMAN_REVIEW` with the provider message visible in the Streamlit UI; it does not
discard the valid research or earlier lesson evidence.

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
