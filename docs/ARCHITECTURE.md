# Architecture

## 1. System context

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Onsera Health Platform                     │
│                                                                     │
│   ┌───────────┐   voice    ┌────────────────┐   REST    ┌────────┐  │
│   │  Patient   │──────────▶│  Intake Agent  │◀─────────│Clinician│  │
│   │ (mobile / │   (.webm)  │   (FastAPI +   │  (approve │(browser│  │
│   │  browser) │            │   LangGraph)   │   /review)│dashboard│ │
│   └───────────┘            └───────┬────────┘           └────────┘  │
│                                    │                                 │
│                       ┌────────────┼────────────┐                   │
│                       ▼            ▼            ▼                   │
│               ┌──────────┐ ┌────────────┐ ┌──────────┐            │
│               │   Groq   │ │ Anthropic  │ │LangGraph │            │
│               │ Whisper  │ │   Claude   │ │MemorySaver│            │
│               │  (STT)   │ │  (LLM)     │ │(state)    │            │
│               └──────────┘ └────────────┘ └──────────┘            │
└─────────────────────────────────────────────────────────────────────┘
```

**External dependencies:**
- **Groq API** — Whisper `whisper-large-v3` for speech-to-text
- **Anthropic API** — Claude Sonnet for signal extraction, meal analysis, and summary generation
- **LangGraph MemorySaver** — in-process checkpoint store for `NodeInterrupt` resumption

---

## 2. Component diagram

```
┌────────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite  :5173)                                    │
│                                                                    │
│  ┌───────────────────┐   ┌──────────────────────────────────────┐ │
│  │  VoiceRecorder    │   │  Dashboard (IntakeCard grid)         │ │
│  │  - MediaRecorder  │   │  - 10s auto-refresh                  │ │
│  │  - 2s job polling │   │  - Risk colour coding                │ │
│  └────────┬──────────┘   └──────────────┬───────────────────────┘ │
│           │ FormData                     │ GET /dashboard           │
│           │ POST /intake                 │                          │
└───────────┼──────────────────────────────┼──────────────────────────┘
            │                              │
            ▼                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + uvicorn  :8000)                                │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  api/main.py                                                 │  │
│  │                                                              │  │
│  │  POST /intake ──────────────────────────────────────────┐   │  │
│  │  GET  /intake/{job_id} ─────────────────────────────┐   │   │  │
│  │  POST /intake/{job_id}/approve ─────────────────┐   │   │   │  │
│  │  GET  /dashboard ───────────────────────────┐   │   │   │   │  │
│  │  GET  /health ──────────────────────────┐   │   │   │   │   │  │
│  │                                         │   │   │   │   │   │  │
│  │  job_store (dict + threading.Lock) ◀────┘───┘───┘───┘   │   │  │
│  │  ThreadPoolExecutor (max 4 workers) ◀───────────────────┘   │  │
│  └──────────────────────────────┬──────────────────────────────┘  │
│                                 │ _run_pipeline / _resume_pipeline  │
│                                 ▼                                  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  agents/intake_graph.py  (LangGraph StateGraph)              │  │
│  │                                                              │  │
│  │  transcribe ──▶ extract_signals ──▶ meal_analysis            │  │
│  │                                          │                   │  │
│  │                                    risk_flag (Python)        │  │
│  │                                          │                   │  │
│  │                          ┌───────────────┴────────────┐      │  │
│  │                    [review=True]               [review=False]│  │
│  │                          │                               │   │  │
│  │                  human_review_gate                        │   │  │
│  │                  (NodeInterrupt ⛔)                       │   │  │
│  │                  MemorySaver checkpoint                   │   │  │
│  │                          │ resume on approve              │   │  │
│  │                          └───────────────┬────────────────┘   │  │
│  │                                    generate_summary            │  │
│  │                                          │                    │  │
│  │                                         END                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. LangGraph pipeline — node detail

| # | Node | Type | Model / Tool | Input | Output |
|---|---|---|---|---|---|
| 1 | `transcribe` | I/O | Groq `whisper-large-v3` | `audio_path` | `transcript` |
| 2 | `extract_signals` | LLM | Claude Sonnet + `ClinicalSignals` schema | `transcript` | `clinical_signals`, `extraction_failed` |
| 3 | `meal_analysis` | LLM | Claude Sonnet + `MealAnalysis` schema | `meals_mentioned` | `meal_data` |
| 4 | `risk_flag` | Python | None | `transcript`, `clinical_signals`, `meal_data` | `risk_level`, `risk_reasons`, `requires_human_review` |
| 5 | `human_review_gate` | Interrupt | `NodeInterrupt` | `risk_level`, `risk_reasons` | *(graph pauses)* |
| 6 | `generate_summary` | LLM | Claude Sonnet | all state fields | `clinical_summary` |

### Conditional routing

```
risk_flag output
      │
      ├─ requires_human_review = True  ──▶  human_review_gate  ──▶  generate_summary
      │
      └─ requires_human_review = False ──────────────────────▶  generate_summary
```

### Risk stratification rules (deterministic, priority order)

```
1. CRITICAL  ←  any of these phrases in raw transcript (case-insensitive):
               "chest pain", "can't breathe", "cannot breathe",
               "difficulty breathing", "severe headache", "vision loss",
               "arm pain", "jaw pain", "suicidal", "self harm",
               "self-harm", "overdose"

2. HIGH      ←  extraction_failed = True  (uncertain data → escalate)
            OR  missed_doses = True  AND  symptoms list is non-empty

3. MEDIUM    ←  glycemic_concern = True  AND  exercise_reported = False

4. LOW       ←  default (no rule matched)
```

---

## 4. Sequence diagrams

### 4a. Normal intake (LOW/MEDIUM risk)

```
Patient      Browser      FastAPI      LangGraph         Groq      Anthropic
   │             │            │             │              │             │
   │──record────▶│            │             │              │             │
   │──submit────▶│            │             │              │             │
   │             │─POST /intake────────────▶│              │             │
   │             │◀──{job_id}──────────────┤              │             │
   │             │            │    invoke(state)           │             │
   │             │            │────────────▶│              │             │
   │             │            │             │─transcribe──▶│             │
   │             │            │             │◀─transcript──┤             │
   │             │            │             │─extract_signals────────────▶
   │             │            │             │◀─ClinicalSignals────────────
   │             │            │             │─meal_analysis──────────────▶
   │             │            │             │◀─MealAnalysis───────────────
   │             │            │             │─risk_flag (Python)          │
   │             │            │             │─generate_summary───────────▶
   │             │            │             │◀─clinical_summary───────────
   │             │◀─poll /job─────────────┤              │             │
   │             │            │  status=complete          │             │
   │◀──dashboard─┤            │             │              │             │
```

### 4b. Critical intake — NodeInterrupt flow

```
Patient      Browser      FastAPI      LangGraph     MemorySaver   Clinician
   │             │            │             │              │             │
   │──submit────▶│─POST /intake─────────────▶│              │             │
   │             │◀──{job_id}──────────────┤              │             │
   │             │            │    invoke(state)           │             │
   │             │            │────────────▶│              │             │
   │             │            │             │ [transcribe → extract →    │
   │             │            │             │  meal_analysis → risk_flag]│
   │             │            │             │─NodeInterrupt──▶│           │
   │             │            │             │  checkpoint     │           │
   │             │◀─GraphInterrupt──────────┤              │             │
   │             │  status=awaiting_review  │              │             │
   │             │            │             │              │             │
   │             │            │             │              │◀──dashboard─┤
   │             │            │             │              │─awaiting────▶
   │             │            │             │              │             │
   │             │            │◀─POST /approve──────────────────────────┤
   │             │            │──resume─────▶│              │             │
   │             │            │             │◀─checkpoint──┤             │
   │             │            │             │ generate_summary ──────────▶
   │             │            │             │◀─clinical_summary───────────
   │             │            │  status=complete           │             │
   │             │            │             │              │─updated─────▶
```

---

## 5. State machine — job lifecycle

```
                    ┌──────────────┐
          submit    │              │
    ─────────────▶  │  processing  │
                    │              │
                    └──────┬───────┘
                           │
               ┌───────────┴────────────┐
               │                        │
    review=True│                        │review=False
               ▼                        ▼
    ┌────────────────────┐    ┌─────────────────┐
    │  awaiting_review   │    │    complete      │
    │  (graph paused)    │    │                 │
    └──────────┬─────────┘    └─────────────────┘
               │ clinician approves
               ▼
         ┌────────────┐
         │ processing │  (only generate_summary runs)
         └─────┬──────┘
               │
               ▼
         ┌────────────┐       ┌───────────┐
         │  complete  │       │   error   │ ← any unhandled exception
         └────────────┘       └───────────┘
```

---

## 6. Data flow

```
[audio bytes]
      │ Groq Whisper
      ▼
[transcript: str]  ──────────────────────────────────┐
      │ Claude Sonnet                                  │ (raw text also
      ▼                                               │  sent to risk_flag
[ClinicalSignals]                                     │  for keyword scan)
  symptoms: list[str]                                 │
  medications: list[MedicationRecord]                 │
  meals_mentioned: list[str]  ────▶ [MealAnalysis]   │
  missed_doses: bool                  glycemic_concern│
  exercise_reported: bool             carb_load       │
  ...                                 ...             │
      │                                  │            │
      └────────────────┬─────────────────┘            │
                       │                              │
                       ▼                              ▼
              [risk_flag (Python)]  ◀─────────────────┘
                risk_level: RiskLevel
                risk_reasons: list[str]
                requires_human_review: bool
                       │
                       ▼
              [generate_summary (Claude)]
                clinical_summary: str (markdown)
```

---

## 7. Deployment architecture

### Docker Compose (development)

```
┌─────────────────────────────────────────────┐
│  Docker host                                │
│                                             │
│  ┌──────────────────┐  ┌─────────────────┐  │
│  │  backend         │  │  frontend       │  │
│  │  :8000           │  │  :5173          │  │
│  │                  │  │                 │  │
│  │  FastAPI         │  │  Vite dev       │  │
│  │  LangGraph       │  │  server         │  │
│  │  MemorySaver     │  │  React SPA      │  │
│  └──────────────────┘  └─────────────────┘  │
│           │                    │             │
│  /tmp/onsera_audio (volume)    │             │
└───────────┼────────────────────┼─────────────┘
            │                    │
            ▼                    ▼
     Groq API             Browser (port 5173)
     Anthropic API
```

### Production target (recommended)

```
                        ┌──────────────┐
                        │     CDN      │
                        │  (frontend   │
                        │   static)    │
                        └──────┬───────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│  Cloud environment                                          │
│                                                             │
│  ┌───────────────┐     ┌───────────────┐                   │
│  │  API Gateway  │────▶│  FastAPI      │                   │
│  │  (auth, rate  │     │  (container)  │                   │
│  │   limiting)   │     └───────┬───────┘                   │
│  └───────────────┘             │                           │
│                       ┌────────┼────────┐                  │
│                       ▼        ▼        ▼                  │
│              ┌──────────┐ ┌────────┐ ┌──────────────┐     │
│              │  Groq    │ │Anthropic│ │ PostgreSQL    │     │
│              │  API     │ │  API   │ │ (jobs + state)│     │
│              └──────────┘ └────────┘ └──────────────┘     │
│                                                             │
│  [replace MemorySaver with AsyncSqliteSaver/Postgres]       │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Non-obvious design decisions

| Decision | Rationale |
|---|---|
| `risk_flag` is pure Python | Safety decisions must be deterministic and auditable. An LLM could hallucinate, be prompt-injected via the transcript, or produce inconsistent output. See [ADR-001](decisions/ADR-001-deterministic-risk-flagging.md). |
| `with_structured_output` (not JSON prompting) | Schema enforced by Anthropic tool-calling. Eliminates brittle string parsing and gives Pydantic validation for free. See [ADR-004](decisions/ADR-004-structured-output.md). |
| Extraction failure → HIGH (not LOW) | The safe failure mode for unknown clinical data is escalation. Silently defaulting to LOW could miss a real emergency. |
| `NodeInterrupt` + `MemorySaver` | True graph pause — generate_summary never runs until approved. Cheaper than re-running the full pipeline. See [ADR-003](decisions/ADR-003-human-in-the-loop.md). |
| `ThreadPoolExecutor` in FastAPI | LangGraph `.invoke()` is synchronous. Running it directly in an async route would block the event loop and prevent any other requests from being served. |
| `threading.Lock` on `job_store` | Python's GIL protects against dict corruption but not semantic races. `dict.update()` from a worker thread is not atomic relative to `GET /dashboard` reads on the asyncio thread. |
