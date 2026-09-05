"""Tests for the background-job helper. Runs against an in-memory sqlite db,
never the real one."""

from __future__ import annotations

import sqlite3
import time

import pytest

from backend.runtime.jobs import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    JobStore,
    run_in_background,
)


@pytest.fixture
def store(tmp_path):
    # A real (temp) file, not ":memory:": JobStore opens and closes a fresh
    # connection per call, matching production - an in-memory db would be
    # destroyed the moment the first call closed its connection.
    db_path = tmp_path / "jobs.sqlite3"

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    return JobStore(connection_factory=connect, ensure_schema=True)


def test_create_starts_a_job_pending_at_zero_progress(store):
    job_id = store.create("run", agent_id="a1")
    job = store.get(job_id)
    assert job.status == STATUS_PENDING
    assert job.progress == 0.0
    assert job.agent_id == "a1"
    assert job.kind == "run"
    assert job.result is None
    assert job.error is None


def test_update_progress_and_status(store):
    job_id = store.create("run", agent_id="a1")
    store.update(job_id, status=STATUS_RUNNING, progress=0.5)
    job = store.get(job_id)
    assert job.status == STATUS_RUNNING
    assert job.progress == 0.5


def test_mark_done_stores_the_result_as_json(store):
    job_id = store.create("run", agent_id="a1")
    store.mark_done(job_id, {"run_id": "run_123", "pass_at_1": 1.0})
    job = store.get(job_id)
    assert job.status == STATUS_DONE
    assert job.progress == 1.0
    assert job.result == {"run_id": "run_123", "pass_at_1": 1.0}


def test_mark_failed_records_the_error(store):
    job_id = store.create("run", agent_id="a1")
    store.mark_failed(job_id, "ValueError: boom")
    job = store.get(job_id)
    assert job.status == STATUS_FAILED
    assert job.error == "ValueError: boom"


def test_mark_progress_computes_a_fraction(store):
    job_id = store.create("run", agent_id="a1")
    store.mark_progress(job_id, 3, 12)
    assert store.get(job_id).progress == 0.25
    store.mark_progress(job_id, 0, 0)
    assert store.get(job_id).progress == 1.0


def test_get_returns_none_for_an_unknown_job(store):
    assert store.get("job_does_not_exist") is None


def test_updated_ts_advances_on_update(store):
    job_id = store.create("run", agent_id="a1")
    before = store.get(job_id).updated_ts
    time.sleep(0.01)
    store.update(job_id, progress=0.1)
    after = store.get(job_id).updated_ts
    assert after >= before


def test_run_in_background_reports_progress_and_success(store):
    def work(progress):
        for done in range(1, 4):
            progress(done, 3)
        return {"ok": True}

    job_id = run_in_background(store, "run", "a1", work)
    for _ in range(200):
        job = store.get(job_id)
        if job.status == STATUS_DONE:
            break
        time.sleep(0.01)
    job = store.get(job_id)
    assert job.status == STATUS_DONE
    assert job.progress == 1.0
    assert job.result == {"ok": True}


def test_run_in_background_reports_failure(store):
    def work(progress):
        raise ValueError("bad case")

    job_id = run_in_background(store, "run", "a1", work)
    for _ in range(200):
        job = store.get(job_id)
        if job.status == STATUS_FAILED:
            break
        time.sleep(0.01)
    job = store.get(job_id)
    assert job.status == STATUS_FAILED
    assert "bad case" in job.error
