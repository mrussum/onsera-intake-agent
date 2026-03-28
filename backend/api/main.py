"""
Onsera Health — FastAPI Backend

Endpoints:
  POST /intake         — Upload audio + patient_id, returns job_id immediately
  GET  /intake/{job_id} — Poll job status and results
  GET  /dashboard      — All completed intakes sorted by risk then recency
  GET  /health         — Service health check

Design notes:
  - LangGraph pipeline runs in a ThreadPoolExecutor to avoid blocking the event loop.
  - Audio files are saved to /tmp/onsera_audio/ and cleaned up after processing.
  - In-memory job_store is sufficient for the demo; swap for Redis/Postgres in prod.
"""

import asyncio
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Onsera Intake Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = Path("/tmp/onsera_audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job store: { job_id: { status, created_at, result, ... } }
job_store: dict[str, dict] = {}

# Thread pool for running the synchronous LangGraph pipeline
_executor = ThreadPoolExecutor(max_workers=4)

# Risk level ordering for dashboard sort (lower = more urgent)
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# Pipeline runner (runs in thread pool)
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, audio_path: str, patient_id: str) -> None:
    """
    Execute the LangGraph intake pipeline synchronously.
    This function is called inside a ThreadPoolExecutor.
    """
    from agents.intake_graph import AgentState, graph

    logger.info("pipeline start | job=%s patient=%s", job_id, patient_id)
    t_start = time.monotonic()

    initial_state: AgentState = {
        "audio_path": audio_path,
        "patient_id": patient_id,
        "transcript": "",
        "clinical_signals": {},
        "meal_data": {},
        "risk_level": "low",
        "risk_reasons": [],
        "clinical_summary": "",
        "requires_human_review": False,
        "human_review_note": "",
        "latency_ms": {},
        "messages": [],
    }

    try:
        result = graph.invoke(initial_state)

        risk_level = result.get("risk_level", "low")
        if hasattr(risk_level, "value"):
            risk_level = risk_level.value

        job_store[job_id].update(
            {
                "status": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "total_ms": round((time.monotonic() - t_start) * 1000, 2),
                "patient_id": patient_id,
                "transcript": result.get("transcript", ""),
                "clinical_signals": result.get("clinical_signals", {}),
                "meal_data": result.get("meal_data", {}),
                "risk_level": risk_level,
                "risk_reasons": result.get("risk_reasons", []),
                "clinical_summary": result.get("clinical_summary", ""),
                "requires_human_review": result.get("requires_human_review", False),
                "human_review_note": result.get("human_review_note", ""),
                "latency_ms": result.get("latency_ms", {}),
            }
        )
        logger.info(
            "pipeline complete | job=%s risk=%s review=%s total=%.0f ms",
            job_id,
            risk_level,
            result.get("requires_human_review", False),
            job_store[job_id]["total_ms"],
        )
    except Exception as exc:
        logger.exception("pipeline error | job=%s", job_id)
        job_store[job_id].update(
            {
                "status": "error",
                "error": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    finally:
        # Clean up audio file
        try:
            os.remove(audio_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# POST /intake
# ---------------------------------------------------------------------------

@app.post("/intake")
async def create_intake(
    audio: UploadFile = File(...),
    patient_id: str = Form(...),
):
    """
    Accept a voice recording and patient ID.
    Saves audio to disk, enqueues the pipeline, returns job_id immediately.
    """
    job_id = str(uuid.uuid4())

    # Save audio file
    suffix = Path(audio.filename).suffix if audio.filename else ".webm"
    audio_path = str(AUDIO_DIR / f"{job_id}{suffix}")
    content = await audio.read()
    with open(audio_path, "wb") as f:
        f.write(content)

    # Register job as pending
    job_store[job_id] = {
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "patient_id": patient_id,
        "job_id": job_id,
    }

    # Fire pipeline in thread pool — does not block event loop
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_pipeline, job_id, audio_path, patient_id)

    logger.info("intake queued | job=%s patient=%s file=%s", job_id, patient_id, audio_path)
    return {"job_id": job_id, "status": "processing"}


# ---------------------------------------------------------------------------
# GET /intake/{job_id}
# ---------------------------------------------------------------------------

@app.get("/intake/{job_id}")
async def get_intake(job_id: str):
    """Poll job status. Returns all available result fields once complete."""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job_store[job_id]


# ---------------------------------------------------------------------------
# GET /dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard")
async def dashboard():
    """
    Return all completed intakes sorted by risk level (critical first)
    then by recency (most recent first).
    Includes a summary_preview (first 200 chars of clinical_summary).
    """
    completed = [j for j in job_store.values() if j.get("status") == "complete"]

    completed.sort(
        key=lambda j: (
            _RISK_ORDER.get(j.get("risk_level", "low"), 3),
            # Negate recency: more recent = smaller sort value
            -(datetime.fromisoformat(j["completed_at"]).timestamp()
              if j.get("completed_at")
              else 0),
        )
    )

    return [
        {
            **j,
            "summary_preview": (j.get("clinical_summary") or "")[:200],
        }
        for j in completed
    ]


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "job_count": len(job_store)}
