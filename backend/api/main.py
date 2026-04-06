"""
Onsera Health — FastAPI Backend

Endpoints:
  POST /intake              — Upload audio + patient_id, returns job_id immediately
  GET  /intake/{job_id}     — Poll job status and results
  POST /intake/{job_id}/approve — Resume a paused (awaiting_review) job
  GET  /dashboard           — All completed intakes sorted by risk then recency
  GET  /health              — Service health check

Design notes:
  - LangGraph pipeline runs in a ThreadPoolExecutor — never blocks the event loop.
  - GraphInterrupt (from NodeInterrupt in human_review_gate) is caught and sets
    job status to "awaiting_review". The approve endpoint resumes the graph.
  - All job state is persisted in SQLite (db/database.py) — survives restarts.
  - Audio files are validated for MIME type and size before processing.
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
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from auth.auth import ensure_admin_key, require_auth  # noqa: E402
from db import database as db  # noqa: E402 — after load_dotenv so DB_PATH env is set

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Onsera Intake Agent", version="1.2.0")

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

# Max audio upload: 50 MB
MAX_AUDIO_BYTES = 50 * 1024 * 1024

# Accepted audio MIME types (browser MediaRecorder sends audio/webm)
ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/mp4",
    "audio/mpeg", "audio/mp3", "audio/x-m4a", "application/octet-stream",
}

# Thread pool for running the synchronous LangGraph pipeline
_executor = ThreadPoolExecutor(max_workers=4)

# Risk level ordering for dashboard sort
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@app.on_event("startup")
def _startup() -> None:
    """Initialise the SQLite database and seed the admin API key on server start."""
    db.init_db()
    logger.info("Database initialised at %s", db.DB_PATH)
    raw_key = ensure_admin_key(db_path=db.DB_PATH)
    if raw_key:
        logger.warning("=" * 60)
        logger.warning("*** ADMIN API KEY (shown once — store it now) ***")
        logger.warning("  %s", raw_key)
        logger.warning("=" * 60)


# ---------------------------------------------------------------------------
# Pipeline runner (runs in thread pool)
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, audio_path: str, patient_id: str) -> None:
    """
    Execute the LangGraph intake pipeline synchronously in a thread.

    Catches GraphInterrupt (raised when human_review_gate fires NodeInterrupt)
    and sets job status to "awaiting_review" with the interrupt payload.
    The graph state is preserved in the MemorySaver checkpointer so the
    approve endpoint can resume from exactly this point.
    """
    from agents.intake_graph import AgentState, graph
    from langgraph.errors import GraphInterrupt

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
        "extraction_failed": False,
        "latency_ms": {},
        "messages": [],
    }

    # thread_id must match job_id so the approve endpoint can resume by job_id
    config = {"configurable": {"thread_id": job_id}}

    try:
        result = graph.invoke(initial_state, config=config)
        _finalise_job(job_id, patient_id, result, t_start)

    except GraphInterrupt as interrupt:
        # human_review_gate fired NodeInterrupt — graph is paused
        interrupt_payload = interrupt.args[0] if interrupt.args else [{}]
        payload = {}
        if hasattr(interrupt_payload, "__iter__"):
            for item in interrupt_payload:
                if hasattr(item, "value") and isinstance(item.value, dict):
                    payload = item.value
                    break

        snapshot = graph.get_state(config)
        snap_values = snapshot.values if snapshot else {}

        risk_level = snap_values.get("risk_level", "high")
        if hasattr(risk_level, "value"):
            risk_level = risk_level.value

        db.update_job(job_id, {
            "status": "awaiting_review",
            "paused_at": datetime.now(timezone.utc).isoformat(),
            "transcript": snap_values.get("transcript", ""),
            "clinical_signals": snap_values.get("clinical_signals", {}),
            "meal_data": snap_values.get("meal_data", {}),
            "risk_level": risk_level,
            "risk_reasons": snap_values.get("risk_reasons", []),
            "requires_human_review": True,
            "human_review_note": payload.get("note", "Awaiting clinician review."),
            "latency_ms": payload.get("latency_ms", snap_values.get("latency_ms", {})),
            "clinical_summary": "",
        })
        logger.warning("pipeline paused (awaiting_review) | job=%s risk=%s", job_id, risk_level)

    except Exception:
        logger.exception("pipeline error | job=%s", job_id)
        db.update_job(job_id, {
            "status": "error",
            "error": "Pipeline execution failed — see server logs.",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass


def _resume_pipeline(job_id: str, clinician_note: str) -> None:
    """
    Resume a paused graph from the MemorySaver checkpoint.
    Called by the approve endpoint in the thread pool.
    """
    from agents.intake_graph import graph
    from langgraph.errors import GraphInterrupt

    logger.info("pipeline resume | job=%s", job_id)
    t_start = time.monotonic()

    config = {"configurable": {"thread_id": job_id}}

    if clinician_note:
        graph.update_state(config, {"human_review_note": clinician_note})

    db.update_job(job_id, {"status": "processing"})

    try:
        result = graph.invoke(None, config=config)
        job = db.get_job(job_id)
        patient_id = job.get("patient_id", "unknown") if job else "unknown"
        _finalise_job(job_id, patient_id, result, t_start)
    except GraphInterrupt:
        logger.error("Second interrupt on resume | job=%s", job_id)
        db.update_job(job_id, {"status": "awaiting_review"})
    except Exception:
        logger.exception("pipeline resume error | job=%s", job_id)
        db.update_job(job_id, {
            "status": "error",
            "error": "Resume execution failed — see server logs.",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })


def _finalise_job(job_id: str, patient_id: str, result: dict, t_start: float) -> None:
    """Normalise and persist a completed pipeline result."""
    risk_level = result.get("risk_level", "low")
    if hasattr(risk_level, "value"):
        risk_level = risk_level.value

    total_ms = round((time.monotonic() - t_start) * 1000, 2)

    db.update_job(job_id, {
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_ms": total_ms,
        "transcript": result.get("transcript", ""),
        "clinical_signals": result.get("clinical_signals", {}),
        "meal_data": result.get("meal_data", {}),
        "risk_level": risk_level,
        "risk_reasons": result.get("risk_reasons", []),
        "clinical_summary": result.get("clinical_summary", ""),
        "requires_human_review": result.get("requires_human_review", False),
        "human_review_note": result.get("human_review_note", ""),
        "latency_ms": result.get("latency_ms", {}),
    })
    logger.info("pipeline complete | job=%s risk=%s total=%.0f ms", job_id, risk_level, total_ms)


# ---------------------------------------------------------------------------
# POST /intake
# ---------------------------------------------------------------------------

@app.post("/intake")
async def create_intake(
    audio: UploadFile = File(...),
    patient_id: str = Form(...),
    _auth: str = Depends(require_auth),
):
    """
    Accept a voice recording and patient ID.
    Validates file type and size, saves to disk, enqueues pipeline.
    Returns job_id immediately — poll GET /intake/{job_id} for status.
    """
    content_type = audio.content_type or ""
    if content_type and content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio type '{content_type}'. "
                   f"Accepted: {', '.join(sorted(ALLOWED_AUDIO_TYPES))}",
        )

    content = await audio.read()

    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large ({len(content) // 1024}KB). Max 50MB.",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    job_id = str(uuid.uuid4())
    suffix = Path(audio.filename).suffix if audio.filename else ".webm"
    audio_path = str(AUDIO_DIR / f"{job_id}{suffix}")

    with open(audio_path, "wb") as f:
        f.write(content)

    db.create_job(job_id, patient_id)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, _run_pipeline, job_id, audio_path, patient_id)

    logger.info("intake queued | job=%s patient=%s bytes=%d", job_id, patient_id, len(content))
    return {"job_id": job_id, "status": "processing"}


# ---------------------------------------------------------------------------
# GET /intake/{job_id}
# ---------------------------------------------------------------------------

@app.get("/intake/{job_id}")
async def get_intake(job_id: str, _auth: str = Depends(require_auth)):
    """Poll job status. Returns full result fields once complete or awaiting_review."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ---------------------------------------------------------------------------
# POST /intake/{job_id}/approve
# ---------------------------------------------------------------------------

@app.post("/intake/{job_id}/approve")
async def approve_intake(
    job_id: str,
    clinician_note: str = Form(default="Approved by clinician."),
    _auth: str = Depends(require_auth),
):
    """
    Resume a paused intake after clinician review.

    Resumes the LangGraph pipeline from the MemorySaver checkpoint —
    only generate_summary runs; all earlier nodes are skipped.
    """
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.get("status") != "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not awaiting review (status: {job.get('status')})",
        )

    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, _resume_pipeline, job_id, clinician_note)

    logger.info("intake approved | job=%s note=%s", job_id, clinician_note[:50])
    return {"job_id": job_id, "status": "processing", "message": "Resuming pipeline after clinician approval."}


# ---------------------------------------------------------------------------
# GET /dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard")
async def dashboard(_auth: str = Depends(require_auth)):
    """
    All intakes (complete + awaiting_review) sorted by risk then recency.
    Includes summary_preview (first 200 chars of clinical_summary).
    """
    jobs = db.list_jobs(statuses=("complete", "awaiting_review"))

    jobs.sort(key=lambda j: (
        _RISK_ORDER.get(j.get("risk_level", "low"), 3),
        -(
            datetime.fromisoformat(
                j.get("completed_at") or j.get("paused_at") or j.get("created_at", "2000-01-01T00:00:00+00:00")
            ).timestamp()
        ),
    ))

    return [
        {**j, "summary_preview": (j.get("clinical_summary") or "")[:200]}
        for j in jobs
    ]


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    counts = db.count_by_status()
    return {"status": "ok", "job_count": sum(counts.values()), "by_status": counts}
