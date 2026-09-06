"""Tests for the /agents/{id}/run, /agents/{id}/runs and /jobs/{id} handlers
and their FastAPI routes."""

from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.runtime.api import list_runs, router, start_run
from backend.runtime.jobs import STATUS_DONE, STATUS_ERROR, JobStore, default_connection_factory


def seed_case_result(
    ledger, *, run_id: str, case_id: str, agent_version: int = 0, **fields
) -> None:
    defaults = {
        "trial": 0,
        "passed": True,
        "score": 1.0,
        "tokens_in": 1,
        "tokens_out": 1,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "steps": 1,
        "tool_calls": 0,
        "tool_errors": 0,
        "transcript_path": f"runs/{run_id}/{case_id}.t0.json",
    }
    defaults.update(fields)
    ledger.emit(
        "case_result",
        agent_id="toy",
        agent_version=agent_version,
        run_id=run_id,
        case_id=case_id,
        **defaults,
    )


def seed_run_finished(ledger, *, run_id: str, agent_version: int = 0, **fields) -> None:
    defaults = {
        "split": "train",
        "trials": 1,
        "pass_at_1": 1.0,
        "pass_pow_k": 1.0,
        "pass_rate_std": 0.0,
        "pass_rate_min": 1.0,
        "pass_rate_max": 1.0,
        "total_cost_usd": 0.0,
        "p50_latency_ms": 0,
        "p95_latency_ms": 0,
        "drift_count": 0,
        "tokens_saved_by_drift": 0,
    }
    defaults.update(fields)
    ledger.emit(
        "run_finished", agent_id="toy", agent_version=agent_version, run_id=run_id, **defaults
    )


def test_list_runs_is_empty_for_an_unknown_agent(ledger):
    assert list_runs("nobody", read_events=ledger.read) == []


def test_list_runs_builds_one_row_per_task_newest_run_first(ledger):
    ledger.emit(
        "run_started",
        agent_id="toy",
        agent_version=0,
        run_id="run_a",
        split="train",
        case_count=1,
        trials=2,
    )
    for trial, passed in enumerate([True, False]):
        seed_case_result(
            ledger,
            run_id="run_a",
            case_id="t1",
            trial=trial,
            passed=passed,
            score=1.0 if trial == 0 else 0.0,
            cost_usd=0.001,
            latency_ms=100,
            transcript_path=f"runs/run_a/t1.t{trial}.json",
            trace_url="https://trace/1" if trial == 0 else None,
        )
    seed_run_finished(ledger, run_id="run_a", trials=2, pass_at_1=0.5, pass_pow_k=0.0)

    summaries = list_runs("toy", read_events=ledger.read)
    assert len(summaries) == 1
    run = summaries[0]
    assert run["run_id"] == "run_a"
    assert run["agent_id"] == "toy"
    assert run["version"] == 0
    assert run["finished_ts"] is not None
    assert run["pass_at_1"] == 0.5
    assert len(run["tasks"]) == 1

    task = run["tasks"][0]
    assert task["case_id"] == "t1"
    # passed_by_trial is the one field that reflects every trial.
    assert task["passed_by_trial"] == [True, False]
    # Everything else is trial 0's value, not an aggregate.
    assert task["score"] == 1.0
    assert task["cost_usd"] == 0.001
    assert task["transcript_path"] == "runs/run_a/t1.t0.json"
    assert task["trace_url"] == "https://trace/1"
    assert task["drift_kind"] is None


def test_a_run_still_in_progress_has_no_finished_ts(ledger):
    ledger.emit(
        "run_started",
        agent_id="toy",
        agent_version=0,
        run_id="run_b",
        split="train",
        case_count=2,
        trials=1,
    )
    seed_case_result(ledger, run_id="run_b", case_id="t1")

    summaries = list_runs("toy", read_events=ledger.read)
    assert len(summaries) == 1
    assert summaries[0]["finished_ts"] is None
    assert len(summaries[0]["tasks"]) == 1


def test_a_task_that_hit_drift_reports_its_kind(ledger):
    ledger.emit(
        "run_started",
        agent_id="toy",
        agent_version=0,
        run_id="run_c",
        split="train",
        case_count=1,
        trials=1,
    )
    drift_id = ledger.emit(
        "drift_detected",
        agent_id="toy",
        agent_version=0,
        run_id="run_c",
        payload={
            "case_id": "t1",
            "trial": 0,
            "step": 3,
            "kind": "loop",
            "evidence": "{}",
            "action": "abort",
            "tokens_at_detection": 100,
        },
    )
    seed_case_result(
        ledger, run_id="run_c", case_id="t1", passed=False, score=0.0, drift_event_id=drift_id
    )

    summaries = list_runs("toy", read_events=ledger.read)
    assert summaries[0]["tasks"][0]["drift_kind"] == "loop"


def test_runs_are_ordered_newest_first(ledger):
    for run_id in ("run_1", "run_2"):
        ledger.emit(
            "run_started",
            agent_id="toy",
            agent_version=0,
            run_id=run_id,
            split="train",
            case_count=0,
            trials=1,
        )
        seed_run_finished(ledger, run_id=run_id)
    summaries = list_runs("toy", read_events=ledger.read)
    assert [s["run_id"] for s in summaries] == ["run_2", "run_1"]


def test_start_run_returns_the_run_id_and_runs_the_real_eval(
    toy_package, evaluator_path, ledger, tmp_path
):
    def always_answers_billing(messages, model, tools=None):
        return {
            "text": '{"category": "billing", "priority": "p1"}',
            "tool_calls": [],
            "usage": {"tokens_in": 5, "tokens_out": 5},
            "cost_usd": 0.0,
        }

    store = JobStore(connection_factory=default_connection_factory(tmp_path / "jobs.sqlite3"))
    run_id = start_run(
        "toy",
        split="train",
        trials=1,
        store=store,
        package=toy_package,
        evaluator_path=evaluator_path,
        complete=always_answers_billing,
        emit=ledger.emit,
        read_events=ledger.read,
        runs_dir=tmp_path / "runs",
    )
    assert run_id.startswith("run_")

    for _ in range(200):
        job = store.get(run_id)
        if job.status in (STATUS_DONE, STATUS_ERROR):
            break
        time.sleep(0.01)
    assert job.status == STATUS_DONE
    assert job.result["run_id"] == run_id
    assert job.result["split"] == "train"
    assert "pass_at_1" in job.result
    assert ledger.of_kind("run_finished")[0]["run_id"] == run_id


# -- routes ---------------------------------------------------------------


def test_routes_are_registered_under_the_expected_paths():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/agents/{agent_id}/run" in paths
    assert "/agents/{agent_id}/runs" in paths
    assert "/jobs/{job_id}" in paths


def test_get_job_returns_404_for_an_unknown_job(monkeypatch, tmp_path):
    from backend.runtime import jobs as jobs_module

    monkeypatch.setattr(
        jobs_module,
        "default_store",
        JobStore(connection_factory=default_connection_factory(tmp_path / "jobs.sqlite3")),
    )
    # api.py imported default_store by reference at module load time, so patch
    # it there too.
    import backend.runtime.api as api_module

    monkeypatch.setattr(api_module, "default_store", jobs_module.default_store)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/jobs/does_not_exist")
    assert response.status_code == 404


def test_get_job_returns_the_job_once_created(tmp_path, monkeypatch):
    import backend.runtime.api as api_module

    store = JobStore(connection_factory=default_connection_factory(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(api_module, "default_store", store)
    job_id = store.create("toy", "run")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["job_id"] == job_id
