# NxtWave Lesson Quality Agent

**Live application:** [https://nxtwave-production-b796.up.railway.app/](https://nxtwave-production-b796.up.railway.app/)

NxtWave Lesson Quality Agent creates a beginner-friendly lesson for any topic, checks the lesson against fixed quality rules, and repairs the lesson when a check fails. Each run keeps its sources, facts, drafts, evaluations, and final result so the work can be reviewed later.

## What the application does

- Researches the requested topic using Tavily.
- Selects relevant sources and creates a compact evidence pack.
- Generates a lesson with Together AI.
- Runs deterministic structure checks and eight quality gates (R1–R8).
- Revises only when there is clear evaluation evidence.
- Stores a reviewable history for every run.
- Learns a small number of reusable guardrails from repeated failures across runs.

## How the workflow works

```text
Topic entered by reviewer
        |
        v
Research plan -> Source discovery -> Source curation -> Grounded knowledge pack
        |
        v
Lesson plan -> First lesson draft
        |
        v
Static checks + R1–R8 semantic evaluation
        |
        +-- All checks pass --> READY_TO_SHIP
        |
        +-- A check fails --> targeted revision --> evaluate again
                                      |
                                      +-- revision budget exhausted --> NEEDS_HUMAN_REVIEW
```

The acceptance criteria do not change between attempts. The lesson is changed using the evaluator's evidence, then measured again using the same rules.

## High-level design

| Layer | Main responsibility |
| --- | --- |
| React UI | Collects a topic, shows workflow progress, source evidence, attempts, quality gates, and the final Markdown lesson. |
| FastAPI adapter | Starts a workflow in the background, exposes run data through APIs/SSE, and serves the built React application. |
| Workflow | Coordinates research, lesson generation, static validation, semantic evaluation, and bounded revisions with LangGraph. |
| Research | Uses Tavily, curates sources, and stores the excerpts used as factual evidence. |
| Generation and evaluation | Uses Together models for planning, lesson generation, revision, and R1–R8 evaluation. |
| Memory | Stores recurring failure patterns in SQLite and injects only relevant learned guardrails into later runs. |

## Prerequisites

- Python 3.11 or newer
- Node.js 22 or newer
- A Together AI API key
- A Tavily API key
- Git

## Run it locally

### 1. Clone the repository

```powershell
git clone https://github.com/DeepData07/NxtWave.git
cd NxtWave
```

### 2. Create and activate a Python virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Create the environment file

```powershell
Copy-Item .env.example .env
```

Open `.env` and add your keys:

```dotenv
TOGETHER_API_KEY=your_together_api_key
TAVILY_API_KEY=your_tavily_api_key
MAX_RETRIES=2
```

The model fields can remain blank because `config.py` supplies defaults. Do not commit `.env` to GitHub.

### 4. Build the web interface

```powershell
cd frontend
npm install
npm run build
cd ..
```

### 5. Start the application

```powershell
.\.venv\Scripts\python.exe -m uvicorn ui_server:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser.

## Useful commands

Run the full deterministic test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run one normal workflow from the terminal:

```powershell
.\.venv\Scripts\python.exe main.py --topic "Introduction to RAG"
```

Run the fixed two-attempt demonstration used for review recordings:

```powershell
$env:ENABLE_DETERMINISTIC_DEMO="true"
.\.venv\Scripts\python.exe main.py --topic "How does RAG help AI answer with facts?"
```

This demonstration does not call Tavily or Together. It always shows Attempt 1 failing R3 and R4, a targeted revision, and Attempt 2 passing all eight gates.

## Quality and correction loop

The workflow requires both of these conditions before shipping a lesson:

1. The deterministic static checks pass.
2. All eight semantic quality gates pass.

Static checks cover required lesson sections, word count, complete learner questions, unmatched code/math blocks, and obvious truncation. The semantic evaluator checks factual grounding, coverage, beginner accessibility, explained jargon, examples, teaching flow, suitable depth, and completeness.

When a lesson fails, the revision prompt receives the exact failed-gate evidence and requested fix. The revised lesson is evaluated again from scratch; the revision model cannot mark its own work as correct.

## Saved run evidence

Each run is stored locally in `data/runs/<run_id>/`. Important files include:

```text
research_plan.json       research scope and search plan
source_manifest.json     selected sources and URLs
canonical_facts.json     facts used for grounding
knowledge_pack.md        readable evidence pack
attempt_0.md             first lesson draft
attempt_1.md             revised lesson, when needed
static_evaluation_*.json deterministic check results
evaluation_*.json        R1–R8 results, evidence, and requested fixes
run_summary.json         final status and attempt history
final_lesson.md          final available lesson
```

The UI reads these same artifacts, so the displayed content and downloadable Markdown file match the evaluated lesson.

## Project structure

```text
frontend/          React lesson-review interface
ui_server.py       FastAPI API, SSE updates, and React static hosting
workflow.py        LangGraph orchestration and retry routing
research.py        research plan, source discovery, curation, and fact packing
lesson.py          lesson planning, generation, revision, and Markdown normalization
evaluation.py      deterministic checks and semantic evaluation contract
memory.py          SQLite-backed recurring-pattern guardrails
llm.py             Together client, token limits, timeout, and fallback handling
main.py            terminal entry point
tests/             deterministic and mocked tests
```

## Deployment

The public application is deployed on Railway. The repository includes a `Dockerfile` that builds the React interface and runs the FastAPI service together. Railway can redeploy the `main` branch to the same public URL after a GitHub push.

## Limits and trade-offs

- Live runs depend on Tavily and Together being available.
- The system has a limited research budget and at most two revisions to control cost and time.
- Semantic evaluation is model-assisted, so source evidence and deterministic checks remain part of the review process.
- Learned guardrails are added only after repeated patterns and are capped to prevent prompt bloat.
- The application is for educational content; high-stakes material still requires subject-matter review.
