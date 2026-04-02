# Onsera Health — Voice-Enabled Patient Intake Agent

An agentic AI pipeline that transcribes patient voice messages, extracts
structured clinical signals, risk-stratifies with deterministic rules, routes
HIGH/CRITICAL cases to human review, and generates clinician-facing summaries.

---

## Architecture overview

```
Patient voice recording
        │
        ▼
  ┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
  │  transcribe  │────▶│ extract_signals  │────▶│ meal_analysis│
  │ Groq Whisper │     │  Claude Sonnet   │     │ Claude Sonnet│
  └─────────────┘     │ (structured JSON)│     └──────┬───────┘
                      └──────────────────┘            │
                                                       ▼
                                               ┌──────────────┐
                                               │  risk_flag   │ ← pure Python
                                               │  (no LLM)    │
                                               └──────┬───────┘
                                                      │
                                      ┌───────────────┴───────────────┐
                                      │ requires_human_review?        │
                                     YES                              NO
                                      │                               │
                                      ▼                               │
                             ┌─────────────────┐                     │
                             │human_review_gate│ ← NodeInterrupt      │
                             │  (graph pauses) │                     │
                             └────────┬────────┘                     │
                                      │ clinician approves            │
                                      └───────────────┬──────────────┘
                                                      ▼
                                            ┌──────────────────┐
                                            │ generate_summary │
                                            │  Claude Sonnet   │
                                            └──────────────────┘
```

## Tech stack

| Layer | Technology |
|---|---|
| Pipeline orchestration | LangGraph 0.2 |
| LLM | Claude Sonnet (via langchain-anthropic) |
| Transcription | Groq Whisper `whisper-large-v3` |
| Structured extraction | Pydantic + `with_structured_output()` |
| Human-in-the-loop | LangGraph `NodeInterrupt` + `MemorySaver` |
| Backend API | FastAPI + uvicorn |
| Frontend | React 18 + Vite |
| Containerisation | Docker + Docker Compose |
| Evaluation | RAGAS-inspired harness with asymmetric safety scoring |

## Quick start

```bash
git clone <repo-url> && cd onsera-intake-agent
cp .env.example .env          # add ANTHROPIC_API_KEY and GROQ_API_KEY
python test_pipeline.py       # verify API keys and pipeline (no mic needed)
docker-compose up --build     # http://localhost:5173
```

See [SETUP.md](SETUP.md) for the full setup guide.

## Documentation

| Document | Description |
|---|---|
| [SETUP.md](SETUP.md) | Installation, configuration, and usage guide |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, diagrams, data flow |
| [docs/USE_CASES.md](docs/USE_CASES.md) | Actor catalogue and detailed use cases |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Functional and non-functional requirements |
| [docs/DATA_MODELS.md](docs/DATA_MODELS.md) | Schema definitions and example payloads |
| [docs/API_SPEC.md](docs/API_SPEC.md) | REST API reference with curl examples |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Test strategy, cases, and safety gates |
| [docs/decisions/](docs/decisions/) | Architecture Decision Records (ADRs) |

## Key design principles

**Safety decisions are never delegated to an LLM.** The `risk_flag` node is
pure Python. Keywords are matched deterministically against the raw transcript.
No hallucination risk on the safety path.

**Extraction failure escalates, never suppresses.** If Claude fails to return
a valid structured response, the patient is routed to HIGH risk and human
review — not silently downgraded to LOW.

**Human-in-the-loop is a first-class graph primitive.** `NodeInterrupt` + 
`MemorySaver` checkpointing means the graph genuinely pauses mid-execution.
On approval, only `generate_summary` runs — no earlier nodes re-execute.

**Async by design.** The FastAPI server never blocks the event loop. The
LangGraph pipeline runs in a `ThreadPoolExecutor`. The dashboard polls on a
10-second interval; individual jobs poll every 2 seconds.

## Repository structure

```
onsera-intake-agent/
├── backend/
│   ├── agents/intake_graph.py     # LangGraph pipeline (6 nodes)
│   ├── api/main.py                # FastAPI server (5 endpoints)
│   ├── evaluation/ragas_harness.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/App.jsx                # React dashboard (single file)
│   ├── Dockerfile
│   └── package.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── USE_CASES.md
│   ├── REQUIREMENTS.md
│   ├── DATA_MODELS.md
│   ├── API_SPEC.md
│   ├── TEST_PLAN.md
│   └── decisions/                 # ADR-001 … ADR-005
├── docker-compose.yml
├── .env.example
├── SETUP.md
└── test_pipeline.py
```
