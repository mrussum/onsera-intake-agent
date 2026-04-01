# Onsera Health — Intake Agent Setup Guide

## What This Project Does

A patient records a voice message about their symptoms, medications, and meals.
The pipeline:

1. **Transcribes** the audio (Groq Whisper `whisper-large-v3`)
2. **Extracts** structured clinical signals (Claude Sonnet via tool-calling)
3. **Analyses** nutritional content (Claude Sonnet)
4. **Risk-stratifies** the patient with deterministic Python rules (no LLM)
5. **Pauses for human review** on HIGH/CRITICAL cases (LangGraph `NodeInterrupt`)
6. **Generates** a structured markdown clinical summary (Claude Sonnet)

A React dashboard shows all intakes sorted by risk, with an approve flow for
paused cases.

---

## Prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Docker + Docker Compose | any recent | `docker --version` |
| Git | any | `git --version` |

You also need two API keys:

| Key | Where to get it | Format |
|---|---|---|
| Anthropic (Claude) | https://console.anthropic.com → API Keys | `sk-ant-api03-…` |
| Groq (Whisper) | https://console.groq.com → API Keys | `gsk_…` |

---

## 1 — Clone and configure environment

```bash
git clone <your-repo-url> onsera-intake-agent
cd onsera-intake-agent

# Copy the example env file
cp .env.example .env
```

Open `.env` and fill in your keys:

```env
ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE
GROQ_API_KEY=gsk_YOUR-KEY-HERE
CLAUDE_MODEL=claude-sonnet-4-5
```

> **Never commit `.env`** — it is listed in `.gitignore`.

---

## 2 — Run the integration tests (no audio needed)

This verifies your API keys and the full pipeline before starting the servers.
The transcription node is mocked so no microphone or audio file is required.

```bash
# From the repo root
cd backend
pip install -r requirements.txt
cd ..

python test_pipeline.py
```

Expected output:

```
✓  API keys validated
   ANTHROPIC_API_KEY: sk-ant-api03…
   GROQ_API_KEY:      gsk_…

TEST 1: Normal intake — metformin, eggs and toast, feeling tired
──────────────────────────────────────────────────────────────
  risk_level            = medium
  requires_human_review = False
  ✓ requires_human_review == False
  PASSED

TEST 2: Critical intake — chest pain, arm pain, missed medication
──────────────────────────────────────────────────────────────
  risk_level            = critical
  requires_human_review = True
  ✓ requires_human_review == True
  ✓ risk_level == 'critical'
  PASSED

ALL TESTS PASSED ✓
```

If either test fails see the **Troubleshooting** section at the bottom.

---

## Option A — Docker Compose (recommended)

Docker runs the backend and frontend in isolated containers with a single command.
Your `.env` keys are passed in automatically.

```bash
# From the repo root
docker-compose up --build
```

First build takes 3–5 minutes (pip install + npm install). Subsequent starts
are fast (layers are cached).

| Service | URL |
|---|---|
| React dashboard | http://localhost:5173 |
| FastAPI backend | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

To stop: `Ctrl+C`, then `docker-compose down`.

To rebuild after code changes:

```bash
docker-compose up --build
```

---

## Option B — Run locally (without Docker)

### Backend

```bash
cd backend

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # macOS / Linux
# or: venv\Scripts\activate     # Windows

pip install -r requirements.txt

# Start the API server
uvicorn api.main:app --reload --port 8000
```

The `--reload` flag restarts the server automatically when you edit Python files.

### Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite starts on http://localhost:5173 and hot-reloads on file changes.

---

## 3 — Use the dashboard

Open **http://localhost:5173** in your browser.

### Submit a voice intake

1. Type a **Patient ID** (e.g. `P1001`) in the input field.
2. Click **Start Recording** — your browser will ask for microphone permission.
3. Speak your check-in message naturally (30–90 seconds works well).
4. Click **Stop Recording**.
5. Click **Submit**.

The status box below the recorder shows live pipeline progress:

```
Processing… (last: extract_signals)
Processing… (last: meal_analysis)
Processing… (last: risk_flag)
Complete ✓
```

The dashboard grid refreshes automatically.

### What to say in a test recording

**Low/medium risk example:**
> "Hi, I'm Sarah, patient P1001. I took my metformin 500mg this morning as
> usual. For breakfast I had eggs on toast. I've been feeling a bit tired but
> nothing serious. I slept about 7 hours. No concerns."

**Critical case (triggers human review):**
> "This is Robert, P3007. I've been having chest pain since this morning and
> some arm pain too. I missed my aspirin and blood pressure medication
> yesterday. I'm very worried. Please call me back."

### Risk colour coding

| Colour | Level | Triggers human review? |
|---|---|---|
| Green | LOW | No |
| Yellow | MEDIUM | No |
| Orange | HIGH | Yes — graph pauses |
| Red | CRITICAL | Yes — graph pauses |

### Approving a paused intake

When a HIGH or CRITICAL intake is submitted, the pipeline pauses before
generating the clinical summary. The card shows an orange **"Awaiting
Clinician Review"** banner.

1. Click the card to open the detail modal.
2. Read the clinical signals and risk reasons.
3. Optionally add a clinician note (e.g. *"Contacted patient — directed to ED"*).
4. Click **Approve & Generate Summary**.
5. The modal polls automatically — the summary appears in ~15 seconds.

---

## API reference

### `POST /intake`
Submit a voice recording for processing.

```bash
curl -X POST http://localhost:8000/intake \
  -F "audio=@/path/to/recording.webm" \
  -F "patient_id=P1001"
```

Response:
```json
{ "job_id": "abc123…", "status": "processing" }
```

### `GET /intake/{job_id}`
Poll for status and results.

```bash
curl http://localhost:8000/intake/abc123
```

Possible `status` values: `processing`, `awaiting_review`, `complete`, `error`.

### `POST /intake/{job_id}/approve`
Resume a paused intake after clinician review.

```bash
curl -X POST http://localhost:8000/intake/abc123/approve \
  -F "clinician_note=Directed patient to call 111"
```

### `GET /dashboard`
All completed and awaiting-review intakes, sorted by risk then recency.

```bash
curl http://localhost:8000/dashboard
```

### `GET /health`
Service health and job count by status.

```bash
curl http://localhost:8000/health
```

---

## Project structure

```
onsera-intake-agent/
├── backend/
│   ├── agents/
│   │   └── intake_graph.py      # LangGraph 6-node pipeline
│   ├── api/
│   │   └── main.py              # FastAPI server
│   ├── evaluation/
│   │   └── ragas_harness.py     # Evaluation framework + golden dataset
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # React clinician dashboard
│   │   └── main.jsx             # React entry point
│   ├── index.html
│   ├── vite.config.js
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example                 # Copy to .env and fill in keys
├── .gitignore
└── test_pipeline.py             # Integration tests (no mic needed)
```

---

## Pipeline internals

```
[audio file]
     │
     ▼
┌──────────────┐
│  transcribe  │  Groq whisper-large-v3  (~1–3s for 60s audio)
└──────┬───────┘
       │ transcript (string)
       ▼
┌─────────────────┐
│ extract_signals │  Claude Sonnet · with_structured_output(ClinicalSignals)
└──────┬──────────┘  Pydantic schema: symptoms, medications, missed_doses, …
       │ clinical_signals (dict)
       ▼
┌───────────────┐
│ meal_analysis │  Claude Sonnet · with_structured_output(MealAnalysis)
└──────┬────────┘  Pydantic schema: calories, glycemic_concern, …
       │ meal_data (dict)
       ▼
┌───────────────┐
│   risk_flag   │  ⚡ PURE PYTHON — no LLM
└──────┬────────┘  CRITICAL → HIGH → MEDIUM → LOW
       │
       ├─── requires_human_review=False ──────────────────────┐
       │                                                       │
       ├─── requires_human_review=True ─────────────────┐     │
       │                                                 │     │
       ▼                                                 ▼     │
┌──────────────────┐                            ┌──────────────────┐
│ human_review_gate│  NodeInterrupt ⛔           │ generate_summary │
│  (pauses graph)  │  graph.invoke(None)         │  Claude Sonnet   │
└──────────────────┘  resumes after approval     └────────┬─────────┘
                                                          │
                                                          ▼
                                                   clinical_summary (markdown)
```

### Risk stratification rules (deterministic, in priority order)

| Priority | Rule | Risk level |
|---|---|---|
| 1 | Any critical keyword in transcript | CRITICAL |
| 2 | `extraction_failed=True` | HIGH |
| 3 | `missed_doses=True` AND symptoms present | HIGH |
| 4 | `glycemic_concern=True` AND no exercise | MEDIUM |
| 5 | Default | LOW |

**Critical keywords:** chest pain, can't breathe, cannot breathe, difficulty
breathing, severe headache, vision loss, arm pain, jaw pain, suicidal,
self harm, self-harm, overdose.

---

## Evaluation harness

The `ragas_harness.py` module provides a golden dataset and scoring functions
for regression testing the pipeline.

```bash
cd backend
python -m evaluation.ragas_harness
```

To run scored evaluation against the live pipeline:

```bash
cd backend
python -c "
import sys, os, tempfile
from unittest.mock import patch
from agents.intake_graph import build_graph, AgentState
from evaluation.ragas_harness import GOLDEN_DATASET, score_extraction, score_safety

def mock_transcribe(transcript):
    def node(state):
        return {'transcript': transcript, 'latency_ms': {**state.get('latency_ms', {}), 'transcribe': 0.0}}
    return node

for case in GOLDEN_DATASET:
    with patch('agents.intake_graph.transcribe', mock_transcribe(case.transcript)):
        g = build_graph()
        result = g.invoke({
            'audio_path': '/dev/null', 'patient_id': case.case_id,
            'transcript': '', 'clinical_signals': {}, 'meal_data': {},
            'risk_level': 'low', 'risk_reasons': [], 'clinical_summary': '',
            'requires_human_review': False, 'human_review_note': '',
            'extraction_failed': False, 'latency_ms': {}, 'messages': [],
        })
    rl = result['risk_level']
    if hasattr(rl, 'value'): rl = rl.value
    ext = score_extraction(result['clinical_signals'], case.expected_signals)
    safe = score_safety(rl, result['requires_human_review'], case.expected_risk, case.must_flag_review)
    print(f'{case.case_id}: extraction={ext:.2f}  safety={safe:.2f}  risk={rl}')
"
```

---

## Dependency notes

### Python version pinning

The `requirements.txt` pins `httpx>=0.25.0,<0.28.0` because `anthropic==0.37.1`
uses the `proxies` parameter removed in `httpx 0.28`. If you upgrade `anthropic`
to `>=0.40.0` you can also remove the `httpx` pin.

### ragas version

`ragas==0.1.21` requires `langchain<0.3` which conflicts with this project's
`langchain==0.3.7`. The requirements file uses `ragas==0.2.6` (first release
with langchain 0.3.x support) instead.

---

## Troubleshooting

### `ANTHROPIC_API_KEY is missing or invalid`
Ensure `.env` exists in the repo root (not inside `backend/`) and that the
key starts with `sk-ant-`. Run `cat .env` to confirm.

### `GROQ_API_KEY is missing or invalid`
Ensure the key starts with `gsk_`. Groq keys are found at console.groq.com
under **API Keys**.

### `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
Your `httpx` version is ≥0.28. Pin it:
```bash
pip install "httpx>=0.25.0,<0.28.0"
```

### `ModuleNotFoundError` when running `test_pipeline.py`
Run from the **repo root**, not from inside `backend/`:
```bash
cd /path/to/onsera-intake-agent
python test_pipeline.py
```

### `OSError: [Errno 28] No space left on device`
The audio temp directory `/tmp/onsera_audio/` is full. Clean it:
```bash
rm -f /tmp/onsera_audio/*
```

### Browser says "Microphone access denied"
- Chrome/Edge: click the camera icon in the address bar → Allow microphone
- Firefox: click the shield icon → Permissions → Allow microphone
- Safari: Settings → Websites → Microphone → Allow for localhost

### Dashboard shows no cards after submission
- Check the browser console for network errors (F12 → Console)
- Confirm the backend is running: `curl http://localhost:8000/health`
- If running Docker, check logs: `docker-compose logs backend`

### `audio/webm` not supported on Safari
Safari does not support `audio/webm`. The recorder falls back gracefully, but
you may see an error. Use Chrome or Firefox for recording. Safari can still
view the dashboard.

### Pipeline takes >60 seconds
Normal pipeline time is 15–25 seconds. If it is consistently slower:
- Check Anthropic API status: https://status.anthropic.com
- Check Groq API status: https://status.groq.com
- Increase the ThreadPoolExecutor `max_workers` in `main.py` if running
  many concurrent intakes.

---

## Environment variables reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key (`sk-ant-…`) |
| `GROQ_API_KEY` | Yes | — | Groq API key (`gsk_…`) |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-5` | Anthropic model ID |
