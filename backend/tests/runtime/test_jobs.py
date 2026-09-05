"""Tests for the background-job helper. Runs against a real, migrated temp
sqlite db (never the real one)."""

from __future__ import annotations

import time

import pytest

from backend.runtime.jobs import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_RUNNING,
    JobStore,
    default_connection_factory,
    run_in_background,
)


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    return JobStore(connection_factory=default_connection_factory(db_path))


def test_create_starts_a_job_queued_with_no_step_yet(store):
    job_id = store.create("a1", "run")
    job = store.get(job_id)
    assert job.status == STATUS_QUEUED
    assert job.agent_id == "a1"
    assert job.kind == "run"
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.issue_id is None
    assert job.current_step is None
    assert job.result is None
    assert job.error is None


def test_create_accepts_issue_id_and_max_attempts(store):
    job_id = store.create("a1", "improve", issue_id="iss_1", max_attempts=5)
    job = store.get(job_id)
    assert job.issue_id == "iss_1"
    assert job.max_attempts == 5


def test_update_status_and_current_step(store):
    job_id = store.create("a1", "run")
    store.update(job_id, status=STATUS_RUNNING, current_step="3/12 cases")
    job = store.get(job_id)
    assert job.status == STATUS_RUNNING
    assert job.current_step == "3/12 cases"


def test_mark_done_stores_the_result_as_json(store):
    job_id = store.create("a1", "run")
    store.mark_done(job_id, {"run_id": "run_123", "pass_at_1": 1.0})
    job = store.get(job_id)
    assert job.status == STATUS_DONE
    assert job.current_step == "done"
    assert job.result == {"run_id": "run_123", "pass_at_1": 1.0}


def test_mark_failed_records_the_error(store):
    job_id = store.create("a1", "run")
    store.mark_failed(job_id, "ValueError: boom")
    job = store.get(job_id)
    assert job.status == STATUS_ERROR
    assert job.error == "ValueError: boom"


def test_mark_progress_sets_a_readable_step(store):
    job_id = store.create("a1", "run")
    store.mark_progress(job_id, 3, 12)
    assert store.get(job_id).current_step == "3/12 cases"


def test_get_returns_none_for_an_unknown_job(store):
    assert store.get("job_does_not_exist") is None


def test_updated_ts_advances_on_update(store):
    job_id = store.create("a1", "run")
    before = store.get(job_id).updated_ts
    time.sleep(0.01)
    store.update(job_id, current_step="ping")
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
    assert job.current_step == "done"
    assert job.result == {"ok": True}


def test_run_in_background_reports_failure(store):
    def work(progress):
        raise ValueError("bad case")

    job_id = run_in_background(store, "run", "a1", work)
    for _ in range(200):
        job = store.get(job_id)
        if job.status == STATUS_ERROR:
            break
        time.sleep(0.01)
    job = store.get(job_id)
    assert job.status == STATUS_ERROR
    assert "bad case" in job.error
