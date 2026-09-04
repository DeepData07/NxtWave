# NxtWave Lesson Quality Agent — TL Verification Pack

## Executive summary

This is a Python/LangGraph lesson-generation agent for a zero-background learner. For each topic it builds a small, fresh, auditable research context; generates a grounded lesson; verifies it with deterministic checks and eight invariant semantic quality gates; repairs evidenced failures within a fixed budget; and persists recurring failures as narrowly scoped guardrails for future runs.

The system is intentionally not a single prompt. It is a bounded control loop whose acceptance criteria do not change during revisions.

## High-level design

```text
Topic
  -> Research plan -> Tavily discovery -> authority curation -> canonical facts
  -> Lesson plan -> lesson generation
  -> deterministic static validation + independent R1-R8 evaluation
       -> both pass: READY_TO_SHIP
       -> either fails: targeted revision -> re-evaluate same criteria
       -> retry budget exhausted: NEEDS_HUMAN_REVIEW

Completed run artifacts -> SQLite failure history -> recurring-pattern distillation
                                      -> capped learned guardrails in later initial prompts
```

Shipping requires both deterministic validation and semantic evaluation to pass. A generation/revision model never self-certifies its own work.

## Low-level design

| Module | Responsibility |
| --- | --- |
| `config.py` | Environment configuration, explicit model/token/time budgets, local data paths. |
| `models.py` | Pydantic contracts for research plans, sources, facts, lesson plans, static/semantic evaluations, and memory. |
| `research.py` | Topic-specific search planning, Tavily discovery, source ranking, curation, fact extraction, and knowledge-pack creation. |
| `prompts.py` | Stable generation policy, invariant evaluator rubric, revision feedback prompts, and guardrail-distillation prompts. |
| `lesson.py` | Lesson planning/generation/revision calls, safe Markdown normalization, and attempt artifact saving. |
| `evaluation.py` | Deterministic checks plus independent structured R1-R8 model evaluation. |
| `workflow.py` | LangGraph orchestration, conditional routing, bounded retries, event recording, and run persistence. |
| `memory.py` | SQLite-backed recurring-failure tracking, guardrail distillation, deduplication, and capped retrieval. |
| `llm.py` | Together request handling, model fallback policy, and error normalization. |
| `main.py` | CLI entry point for normal and controlled fault-demo runs. |

## Quality-control loop

```text
Stable base policy + topic-specific grounded facts + active learned guardrails
  -> lesson attempt N
  -> static checks (structure, required sections, learner questions, obvious completeness)
  -> same independent R1-R8 evaluator on every attempt
  -> failure packet containing only evidence/reasons/required fixes
  -> complete replacement lesson attempt N+1
```

The eight semantic gates remain invariant:

| Gate | Invariant criterion |
| --- | --- |
| R1 | Factual Accuracy |
| R2 | Essential Coverage |
| R3 | Beginner Accessibility |
| R4 | Jargon Explainability |
| R5 | Learning by Example |
| R6 | Teaching Flow |
| R7 | Appropriate Depth |
| R8 | Standalone and Complete |

With `MAX_RETRIES=2`, the workflow makes one initial attempt plus at most two targeted revisions: **three attempts maximum**. It stops early on a pass. Otherwise it reports `NEEDS_HUMAN_REVIEW`; it never loops forever.

## Self-correction versus self-evolution

- **Within one run:** evaluator evidence repairs the current lesson. The rubric does not change.
- **Across separate runs:** repeated failures for the same gate are stored in SQLite. Once a pattern reaches the configured threshold (default two distinct runs), the system creates a reusable, auditable guardrail. At most five relevant active guardrails are injected into a future initial-generation prompt.

This prevents one-off feedback from permanently changing behavior and prevents unbounded prompt growth.

## Evidence and auditability

Every run is persisted under `data/runs/<run_id>/`. Important artifacts include:

```text
research_plan.json       source_manifest.json        canonical_facts.json
knowledge_pack.md        lesson_plan.json            prompt_<n>.md
attempt_<n>.md           static_evaluation_<n>.json  evaluation_<n>.json
rejection_log.json       events.json                 run_summary.json
final_lesson.md          memory_update.json          workflow_error.json (on failure)
```

Only the specific source excerpts that support selected facts are stored, with source IDs and URLs. Raw whole webpages are not retained.

## Trade-offs and limitations

| Decision | Benefit | Trade-off |
| --- | --- | --- |
| Fresh per-run research context rather than a vector database | Simpler, lower operational cost, directly auditable evidence for a small source set | Does not provide long-lived semantic retrieval across a large document corpus |
| Model-assisted semantic evaluation plus deterministic checks | Captures pedagogical quality while retaining hard structural safeguards | Semantic judgments remain probabilistic and should not replace expert review in high-stakes domains |
| Bounded retries | Predictable cost/latency; avoids runaway loops | A hard topic/provider issue can end in human review instead of infinite repair |
| Explicit output/token/time budgets | Cost control and provider safety | Short budgets can cause truncation; the static completeness checks and concise completion policy reduce this risk |
| Learned guardrails after repeated evidence only | Avoids one-off overfitting; remains explainable | Learning is intentionally gradual rather than immediately adaptive |
| Provider fallback | Better availability when a model is temporarily unavailable | Fallback model output can differ in quality; every result still goes through the same gates |

## How to run

Requirements: Python 3.11+, Together API key, and Tavily API key for live research.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set at minimum:

```dotenv
TOGETHER_API_KEY=your_key
TAVILY_API_KEY=your_key
MAX_RETRIES=2
```

Run deterministic tests (no live-model credits used):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run a normal live workflow:

```powershell
.\.venv\Scripts\python.exe main.py --topic "Introduction to RAG"
```

Run a reliable correction-loop demonstration. The fault applies only to attempt 0, so later revisions are clean:

```powershell
.\.venv\Scripts\python.exe main.py --topic "Introduction to RAG" --fault overly_technical_language
```

## Verification status

At pack creation, the deterministic suite passed:

```text
57 passed, 2 third-party deprecation warnings
```

The tests use mocks for model/provider behavior, so the suite is deterministic and does not consume API credits.

## UI note (UI source deliberately excluded)

The application has a separate light React viewer over the existing FastAPI contract. It shows the persisted workflow timeline, attempts, static checks, gate evidence, targeted revisions, and final lesson. Lesson Markdown uses GFM tables and KaTeX math rendering. It is a presentation layer only: workflow decisions, evaluation, retry routing, research, and memory remain in the Python backend.

## Included source in this pack

The ZIP intentionally excludes `frontend/`, `ui/`, `app.py`, generated runs, SQLite data, virtual environments, and secrets. It includes the core backend modules, configuration template, requirements, CLI entry point, this document, and representative tests for research, workflow routing, evaluation, lessons, memory, models, and provider handling.
