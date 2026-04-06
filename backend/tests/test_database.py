"""
Unit tests for the SQLite persistence layer (db/database.py).

Uses :memory: databases — no filesystem side effects, fully isolated.
"""

import pytest
from db.database import (
    count_by_status,
    create_job,
    get_job,
    init_db,
    list_jobs,
    update_job,
)


@pytest.fixture()
def fresh_db(tmp_path):
    """Each test gets a fresh isolated SQLite file via pytest's tmp_path."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "idempotent.db")
    init_db(db_path)
    init_db(db_path)  # Second call must not raise


# ---------------------------------------------------------------------------
# create_job / get_job
# ---------------------------------------------------------------------------

class TestCreateAndGet:
    def test_created_job_is_retrievable(self, fresh_db):
        create_job("job-1", "P001", fresh_db)
        job = get_job("job-1", fresh_db)
        assert job is not None
        assert job["job_id"] == "job-1"
        assert job["patient_id"] == "P001"
        assert job["status"] == "processing"

    def test_get_nonexistent_job_returns_none(self, fresh_db):
        assert get_job("does-not-exist", fresh_db) is None

    def test_default_json_fields_are_empty_collections(self, fresh_db):
        create_job("job-2", "P002", fresh_db)
        job = get_job("job-2", fresh_db)
        assert job["clinical_signals"] == {}
        assert job["meal_data"] == {}
        assert job["risk_reasons"] == []
        assert job["latency_ms"] == {}

    def test_default_bool_fields_are_false(self, fresh_db):
        create_job("job-3", "P003", fresh_db)
        job = get_job("job-3", fresh_db)
        assert job["requires_human_review"] is False
        assert job["extraction_failed"] is False

    def test_created_at_is_set(self, fresh_db):
        create_job("job-4", "P004", fresh_db)
        job = get_job("job-4", fresh_db)
        assert job["created_at"] is not None
        assert "T" in job["created_at"]  # ISO 8601


# ---------------------------------------------------------------------------
# update_job
# ---------------------------------------------------------------------------

class TestUpdateJob:
    def test_update_status(self, fresh_db):
        create_job("job-u1", "P010", fresh_db)
        update_job("job-u1", {"status": "complete"}, fresh_db)
        assert get_job("job-u1", fresh_db)["status"] == "complete"

    def test_update_json_fields_round_trip(self, fresh_db):
        create_job("job-u2", "P011", fresh_db)
        signals = {"missed_doses": True, "symptoms": ["headache", "dizziness"]}
        latency = {"transcribe": 120.5, "extract_signals": 340.0}
        update_job("job-u2", {"clinical_signals": signals, "latency_ms": latency}, fresh_db)

        job = get_job("job-u2", fresh_db)
        assert job["clinical_signals"] == signals
        assert job["latency_ms"] == latency

    def test_update_bool_fields(self, fresh_db):
        create_job("job-u3", "P012", fresh_db)
        update_job("job-u3", {"requires_human_review": True, "extraction_failed": True}, fresh_db)
        job = get_job("job-u3", fresh_db)
        assert job["requires_human_review"] is True
        assert job["extraction_failed"] is True

    def test_update_does_not_overwrite_job_id(self, fresh_db):
        create_job("job-u4", "P013", fresh_db)
        update_job("job-u4", {"job_id": "hacked", "status": "complete"}, fresh_db)
        assert get_job("job-u4", fresh_db) is not None  # original key still works
        assert get_job("hacked", fresh_db) is None

    def test_updated_at_is_refreshed(self, fresh_db):
        create_job("job-u5", "P014", fresh_db)
        original = get_job("job-u5", fresh_db)["updated_at"]
        update_job("job-u5", {"status": "complete"}, fresh_db)
        # updated_at should be >= original (could be equal in fast test runs)
        assert get_job("job-u5", fresh_db)["updated_at"] >= original

    def test_empty_update_is_safe(self, fresh_db):
        create_job("job-u6", "P015", fresh_db)
        update_job("job-u6", {}, fresh_db)  # must not raise
        assert get_job("job-u6", fresh_db)["status"] == "processing"

    def test_update_risk_reasons_list(self, fresh_db):
        create_job("job-u7", "P016", fresh_db)
        reasons = ["Critical keyword detected: 'chest pain'", "Missed doses with active symptoms"]
        update_job("job-u7", {"risk_reasons": reasons}, fresh_db)
        assert get_job("job-u7", fresh_db)["risk_reasons"] == reasons


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    def test_returns_only_matching_statuses(self, fresh_db):
        create_job("jl-1", "P020", fresh_db)
        create_job("jl-2", "P021", fresh_db)
        update_job("jl-1", {"status": "complete"}, fresh_db)
        update_job("jl-2", {"status": "awaiting_review"}, fresh_db)
        create_job("jl-3", "P022", fresh_db)  # still 'processing'

        results = list_jobs(statuses=("complete", "awaiting_review"), db_path=fresh_db)
        job_ids = {j["job_id"] for j in results}
        assert "jl-1" in job_ids
        assert "jl-2" in job_ids
        assert "jl-3" not in job_ids

    def test_empty_db_returns_empty_list(self, fresh_db):
        assert list_jobs(db_path=fresh_db) == []

    def test_custom_status_filter(self, fresh_db):
        create_job("jl-4", "P023", fresh_db)
        update_job("jl-4", {"status": "error"}, fresh_db)
        results = list_jobs(statuses=("error",), db_path=fresh_db)
        assert len(results) == 1
        assert results[0]["job_id"] == "jl-4"


# ---------------------------------------------------------------------------
# count_by_status
# ---------------------------------------------------------------------------

class TestCountByStatus:
    def test_counts_correctly(self, fresh_db):
        create_job("jc-1", "P030", fresh_db)
        create_job("jc-2", "P031", fresh_db)
        create_job("jc-3", "P032", fresh_db)
        update_job("jc-1", {"status": "complete"}, fresh_db)
        update_job("jc-2", {"status": "complete"}, fresh_db)
        update_job("jc-3", {"status": "awaiting_review"}, fresh_db)

        counts = count_by_status(fresh_db)
        assert counts["complete"] == 2
        assert counts["awaiting_review"] == 1

    def test_empty_db_returns_empty_dict(self, fresh_db):
        assert count_by_status(fresh_db) == {}
