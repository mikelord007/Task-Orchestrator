"""Tests for the background-job helper. Runs against a real, migrated temp
sqlite db (never the real one)."""

from __future__ import annotations

import time
from threading import Event

import pytest

from backend.runtime.jobs import (
    INTERRUPTED_ERROR,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_RUNNING,
    JobStore,
    default_connection_factory,
    mark_incomplete_jobs_interrupted,
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
    store.mark_progress(job_id, 3, 3)
    store.mark_done(job_id, {"run_id": "run_123", "pass_at_1": 1.0})
    job = store.get(job_id)
    assert job.status == STATUS_DONE
    assert job.step_label() == "done"
    # The last mark_progress before completion already reported done == total.
    assert job.progress() == {"done": 3, "total": 3}
    assert job.result == {"run_id": "run_123", "pass_at_1": 1.0}


def test_mark_failed_records_the_error(store):
    job_id = store.create("a1", "run")
    store.mark_failed(job_id, "ValueError: boom")
    job = store.get(job_id)
    assert job.status == STATUS_ERROR
    assert job.error == "ValueError: boom"


def test_restart_marks_only_incomplete_jobs_as_interrupted(store):
    queued_id = store.create("a1", "run")
    running_id = store.create("a1", "improve")
    done_id = store.create("a1", "run")
    store.mark_running(running_id)
    store.mark_done(done_id, {"ok": True})

    connection = store._connect()
    try:
        assert mark_incomplete_jobs_interrupted(connection) == 2
    finally:
        connection.close()

    assert store.get(queued_id).status == STATUS_ERROR
    assert store.get(queued_id).error == INTERRUPTED_ERROR
    assert store.get(running_id).status == STATUS_ERROR
    assert store.get(running_id).error == INTERRUPTED_ERROR
    assert store.get(done_id).status == STATUS_DONE
    assert store.get(done_id).error is None


def test_mark_progress_sets_a_readable_step(store):
    job_id = store.create("a1", "run")
    store.mark_progress(job_id, 3, 12)
    job = store.get(job_id)
    assert job.progress() == {"done": 3, "total": 12}
    assert job.step_label() == "3/12 cases"


def test_progress_defaults_to_zero_before_any_progress_is_reported(store):
    job_id = store.create("a1", "run")
    assert store.get(job_id).progress() == {"done": 0, "total": 0}


def test_payload_matches_the_frontend_job_shape(store):
    job_id = store.create("a1", "run")
    store.mark_progress(job_id, 1, 4)
    payload = store.get(job_id).payload()
    assert payload["job_id"] == job_id
    assert payload["kind"] == "run"
    assert payload["status"] == STATUS_QUEUED
    assert payload["progress"] == {"done": 1, "total": 4}
    assert "result" in payload and "error" in payload


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
    assert job.step_label() == "done"
    assert job.progress() == {"done": 3, "total": 3}
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


def test_background_job_keeps_the_ledger_selected_at_start(tmp_path, monkeypatch):
    primary_path = tmp_path / "primary.sqlite3"
    redirected_path = tmp_path / "redirected.sqlite3"
    monkeypatch.setenv("TO_DB_PATH", str(primary_path))
    dynamic_store = JobStore()
    started = Event()
    release = Event()

    def work(progress):
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    job_id = run_in_background(dynamic_store, "run", "a1", work)
    assert started.wait(timeout=2)

    monkeypatch.setenv("TO_DB_PATH", str(redirected_path))
    redirected_store = JobStore(default_connection_factory(redirected_path))
    assert redirected_store.get("missing") is None
    release.set()

    primary_store = JobStore(default_connection_factory(primary_path))
    for _ in range(200):
        job = primary_store.get(job_id)
        if job is not None and job.status == STATUS_DONE:
            break
        time.sleep(0.01)

    assert primary_store.get(job_id).status == STATUS_DONE
    assert redirected_store.get(job_id) is None
