"""
Onsera Health — SQLite persistence layer.

Replaces the in-memory job_store dict with a durable SQLite database.
Each function opens its own connection — safe for concurrent access from
the FastAPI event loop and the ThreadPoolExecutor pipeline threads.

WAL mode is enabled on init for better concurrent-reader performance
(readers don't block writers and vice versa).

Environment:
    DB_PATH — path to the SQLite file (default: /tmp/onsera_intake.db)
              Set to :memory: in tests for an in-process ephemeral DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DB_PATH: str = os.getenv("DB_PATH", "/tmp/onsera_intake.db")

# Fields whose values are dicts/lists and must be JSON-encoded for storage
_JSON_FIELDS: frozenset[str] = frozenset(
    {"clinical_signals", "meal_data", "risk_reasons", "latency_ms"}
)

# Fields stored as INTEGER 0/1 in SQLite
_BOOL_FIELDS: frozenset[str] = frozenset(
    {"requires_human_review", "extraction_failed"}
)

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id                TEXT PRIMARY KEY,
    patient_id            TEXT    NOT NULL,
    status                TEXT    NOT NULL DEFAULT 'processing',
    transcript            TEXT    NOT NULL DEFAULT '',
    clinical_signals      TEXT    NOT NULL DEFAULT '{}',
    meal_data             TEXT    NOT NULL DEFAULT '{}',
    risk_level            TEXT    NOT NULL DEFAULT 'low',
    risk_reasons          TEXT    NOT NULL DEFAULT '[]',
    clinical_summary      TEXT    NOT NULL DEFAULT '',
    requires_human_review INTEGER NOT NULL DEFAULT 0,
    human_review_note     TEXT    NOT NULL DEFAULT '',
    extraction_failed     INTEGER NOT NULL DEFAULT 0,
    latency_ms            TEXT    NOT NULL DEFAULT '{}',
    error                 TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    completed_at          TEXT,
    paused_at             TEXT,
    total_ms              REAL
);
"""


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create the jobs table and enable WAL mode. Safe to call multiple times."""
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(_CREATE_JOBS_TABLE)
        conn.commit()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _encode(field: str, value: Any) -> Any:
    """Convert Python value to a SQLite-compatible type."""
    if field in _JSON_FIELDS:
        return json.dumps(value if value is not None else ({} if field != "risk_reasons" else []))
    if field in _BOOL_FIELDS:
        return 1 if value else 0
    return value


def _decode_row(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict with types restored."""
    d = dict(row)
    for field in _JSON_FIELDS:
        if field in d and d[field] is not None:
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = {} if field != "risk_reasons" else []
    for field in _BOOL_FIELDS:
        if field in d and d[field] is not None:
            d[field] = bool(d[field])
    return d


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_job(job_id: str, patient_id: str, db_path: str = DB_PATH) -> None:
    """Insert a new job row with status='processing'."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, patient_id, status, created_at, updated_at)
            VALUES (?, ?, 'processing', ?, ?)
            """,
            (job_id, patient_id, now, now),
        )
        conn.commit()


def get_job(job_id: str, db_path: str = DB_PATH) -> dict | None:
    """Fetch a job by ID. Returns None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _decode_row(row) if row else None


def update_job(job_id: str, fields: dict, db_path: str = DB_PATH) -> None:
    """
    Update arbitrary fields on a job row.

    Handles JSON serialisation for dict/list fields and bool→int conversion.
    Always writes the current UTC timestamp to updated_at.
    """
    if not fields:
        return

    # Never allow overwriting the primary key
    fields.pop("job_id", None)

    # Encode values for SQLite storage
    encoded = {k: _encode(k, v) for k, v in fields.items()}
    encoded["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in encoded)
    values = list(encoded.values()) + [job_id]

    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE jobs SET {set_clause} WHERE job_id = ?",  # noqa: S608
            values,
        )
        conn.commit()


def list_jobs(
    statuses: tuple[str, ...] = ("complete", "awaiting_review"),
    db_path: str = DB_PATH,
) -> list[dict]:
    """Return all jobs whose status is in `statuses`, newest first."""
    placeholders = ",".join("?" * len(statuses))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC",  # noqa: S608
            list(statuses),
        ).fetchall()
    return [_decode_row(r) for r in rows]


def count_by_status(db_path: str = DB_PATH) -> dict[str, int]:
    """Return a {status: count} dict for the health endpoint."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}
