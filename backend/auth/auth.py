"""
Onsera Health — API key authentication.

Keys are generated as 'ons_' + 32 random hex chars (128-bit entropy).
Only the SHA-256 hash is stored in the database — the raw key is shown
once at startup or generation time and is never recoverable afterwards.

Both header formats are accepted:
  X-API-Key: ons_abc123...
  Authorization: Bearer ons_abc123...

GET /health is intentionally excluded from authentication so the Docker
healthcheck (which cannot pass custom headers) continues to work.

Environment:
    ADMIN_API_KEY — if set, this key is seeded into the DB on startup.
                    If not set and no keys exist, a key is auto-generated
                    and printed to the server log — look for the line
                    starting with "*** ADMIN API KEY ***".
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

_XAPIKEY_SCHEME = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER_SCHEME = APIKeyHeader(name="Authorization", auto_error=False)


# ---------------------------------------------------------------------------
# Key utilities
# ---------------------------------------------------------------------------

def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key() -> str:
    """Generate a new random API key: 'ons_' + 32 hex chars (128-bit entropy)."""
    return "ons_" + secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

def ensure_admin_key(db_path: str) -> str | None:
    """
    Called at server startup. Guarantees at least one API key is in the DB.

    Priority order:
      1. ADMIN_API_KEY env var is set → seed it into DB (idempotent); return None.
      2. Keys already exist in DB (from a prior run) → nothing to do; return None.
      3. No keys at all → auto-generate one, store it, return the raw key.
         The caller MUST log this key — it cannot be retrieved later.
    """
    from db import database as db

    raw_env = os.getenv("ADMIN_API_KEY", "").strip()
    if raw_env:
        key_hash = hash_key(raw_env)
        if not db.get_api_key(key_hash, db_path=db_path):
            db.create_api_key(key_hash, label="admin (from ADMIN_API_KEY env)", db_path=db_path)
            logger.info("Admin API key seeded from ADMIN_API_KEY env var.")
        return None

    if db.api_key_count(db_path=db_path) > 0:
        return None  # Keys already present from a previous run

    raw_key = generate_key()
    db.create_api_key(hash_key(raw_key), label="admin (auto-generated)", db_path=db_path)
    return raw_key


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def require_auth(
    x_api_key: str | None = Security(_XAPIKEY_SCHEME),
    authorization: str | None = Security(_BEARER_SCHEME),
) -> str:
    """
    FastAPI dependency — validates the incoming API key.

    Accepts:
      - X-API-Key: <key>
      - Authorization: Bearer <key>

    Returns the key_hash on success (useful for audit logging downstream).
    Raises 401 if no key is supplied, 403 if the key is invalid.
    """
    from db import database as db

    raw_key: str | None = None
    if x_api_key:
        raw_key = x_api_key
    elif authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization[7:]

    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="API key required — pass as 'X-API-Key' header or 'Authorization: Bearer <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hash_key(raw_key)
    if not db.validate_api_key(key_hash):
        raise HTTPException(status_code=403, detail="Invalid API key.")

    db.touch_api_key(key_hash)
    return key_hash
