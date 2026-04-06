"""
Unit tests for the API key authentication module (auth/auth.py).

These tests exercise key generation, hashing, DB seeding, and the
ensure_admin_key startup flow. The FastAPI require_auth dependency is
tested indirectly — full endpoint auth coverage belongs in API-level tests.
"""

import os
import pytest
from auth.auth import ensure_admin_key, generate_key, hash_key
from db.database import (
    api_key_count,
    create_api_key,
    get_api_key,
    init_db,
    validate_api_key,
)


@pytest.fixture()
def fresh_db(tmp_path):
    db_path = str(tmp_path / "auth_test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Key generation and hashing
# ---------------------------------------------------------------------------

class TestKeyUtils:
    def test_generate_key_has_ons_prefix(self):
        key = generate_key()
        assert key.startswith("ons_")

    def test_generate_key_has_expected_length(self):
        # "ons_" (4) + 64 hex chars = 68 total
        assert len(generate_key()) == 68

    def test_generate_key_is_unique(self):
        keys = {generate_key() for _ in range(50)}
        assert len(keys) == 50  # No collisions in 50 attempts

    def test_hash_key_returns_hex_string(self):
        h = hash_key("ons_abc123")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_key_is_deterministic(self):
        assert hash_key("ons_abc") == hash_key("ons_abc")

    def test_different_keys_produce_different_hashes(self):
        assert hash_key("ons_aaa") != hash_key("ons_bbb")

    def test_hash_key_is_not_reversible(self):
        raw = generate_key()
        h = hash_key(raw)
        assert raw not in h  # Hash must not contain the raw key


# ---------------------------------------------------------------------------
# ensure_admin_key — startup seeding
# ---------------------------------------------------------------------------

class TestEnsureAdminKey:
    def test_auto_generates_key_when_db_is_empty(self, fresh_db):
        raw_key = ensure_admin_key(fresh_db)
        assert raw_key is not None
        assert raw_key.startswith("ons_")

    def test_auto_generated_key_is_stored_in_db(self, fresh_db):
        raw_key = ensure_admin_key(fresh_db)
        assert validate_api_key(hash_key(raw_key), db_path=fresh_db)

    def test_returns_none_when_keys_already_exist(self, fresh_db):
        # Seed a key manually first
        raw_key = generate_key()
        create_api_key(hash_key(raw_key), label="test", db_path=fresh_db)
        # ensure_admin_key should not generate a new one
        result = ensure_admin_key(fresh_db)
        assert result is None
        assert api_key_count(fresh_db) == 1  # Still only one key

    def test_seeds_env_key_when_admin_api_key_env_set(self, fresh_db, monkeypatch):
        raw_key = generate_key()
        monkeypatch.setenv("ADMIN_API_KEY", raw_key)
        result = ensure_admin_key(fresh_db)
        assert result is None  # Env key — caller already knows it
        assert validate_api_key(hash_key(raw_key), db_path=fresh_db)

    def test_env_key_seeding_is_idempotent(self, fresh_db, monkeypatch):
        raw_key = generate_key()
        monkeypatch.setenv("ADMIN_API_KEY", raw_key)
        ensure_admin_key(fresh_db)
        ensure_admin_key(fresh_db)  # Second call must not raise or duplicate
        assert api_key_count(fresh_db) == 1

    def test_does_not_auto_generate_when_env_key_set(self, fresh_db, monkeypatch):
        raw_key = generate_key()
        monkeypatch.setenv("ADMIN_API_KEY", raw_key)
        result = ensure_admin_key(fresh_db)
        assert result is None  # Must not return an auto-generated key


# ---------------------------------------------------------------------------
# DB-level key validation
# ---------------------------------------------------------------------------

class TestApiKeyValidation:
    def test_valid_key_passes(self, fresh_db):
        raw = generate_key()
        create_api_key(hash_key(raw), label="test key", db_path=fresh_db)
        assert validate_api_key(hash_key(raw), db_path=fresh_db) is True

    def test_unknown_key_fails(self, fresh_db):
        assert validate_api_key(hash_key("ons_doesnotexist"), db_path=fresh_db) is False

    def test_get_api_key_returns_metadata(self, fresh_db):
        raw = generate_key()
        create_api_key(hash_key(raw), label="my key", db_path=fresh_db)
        record = get_api_key(hash_key(raw), db_path=fresh_db)
        assert record is not None
        assert record["label"] == "my key"
        assert record["created_at"] is not None
        assert record["last_used_at"] is None  # Not used yet

    def test_get_api_key_returns_none_for_unknown(self, fresh_db):
        assert get_api_key("nonexistent_hash", db_path=fresh_db) is None

    def test_duplicate_key_insert_is_ignored(self, fresh_db):
        raw = generate_key()
        h = hash_key(raw)
        create_api_key(h, label="first", db_path=fresh_db)
        create_api_key(h, label="duplicate", db_path=fresh_db)  # Must not raise
        assert api_key_count(fresh_db) == 1
