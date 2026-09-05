"""Tests for the plain-function handlers behind /agents/{id}/run and
/agents/{id}/runs."""

from __future__ import annotations

import sqlite3
import time

from backend.runtime.api import list_runs, start_run
from backend.runtime.jobs import STATUS_DONE, STATUS_FAILED, JobStore


def test_list_runs_is_empty_for_an_unknown_agent(ledger):
    assert list_runs("nobody", read_events=ledger.read) == []


def test_list_runs_builds_one_row_per_case_newest_run_first(ledger):
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
        ledger.emit(
            "case_result",
            agent_id="toy",
            agent_version=0,
            run_id="run_a",
            case_id="t1",
            trial=trial,
            passed=passed,
            score=1.0 if passed else 0.0,
            cost_usd=0.001,
            latency_ms=100.0,
            transcript_path=f"runs/run_a/t1.t{trial}.json",
            trace_url="https://trace/1" if trial == 0 else None,
            drift_event_id=None,
        )
    ledger.emit(
        "run_finished",
        agent_id="toy",
        agent_version=0,
        run_id="run_a",
        split="train",
        trials=2,
        pass_at_1=0.5,
        pass_pow_k=0.0,
        pass_rate_std=0.5,
        pass_rate_min=0.0,
        pass_rate_max=1.0,
        total_cost_usd=0.002,
        p50_latency_ms=100,
        p95_latency_ms=100,
        drift_count=0,
        tokens_saved_by_drift=0,
    )

    listings = list_runs("toy", read_events=ledger.read)
    assert len(listings) == 1
    run = listings[0]
    assert run["run_id"] == "run_a"
    assert run["finished"] is True
    assert run["pass_at_1"] == 0.5
    assert len(run["cases"]) == 1
    row = run["cases"][0]
    assert row["case_id"] == "t1"
    assert row["passed_by_trial"] == [True, False]
    assert row["score"] == 0.5
    assert row["cost_usd"] == 0.002
    assert row["transcript_paths"] == ["runs/run_a/t1.t0.json", "runs/run_a/t1.t1.json"]
    assert row["trace_url"] == "https://trace/1"
    assert row["drift"] is False


def test_a_run_still_in_progress_is_listed_with_finished_false(ledger):
    ledger.emit(
        "run_started",
        agent_id="toy",
        agent_version=0,
        run_id="run_b",
        split="train",
        case_count=2,
        trials=1,
    )
    ledger.emit(
        "case_result",
        agent_id="toy",
        agent_version=0,
        run_id="run_b",
        case_id="t1",
        trial=0,
        passed=True,
        score=1.0,
        cost_usd=0.0,
        latency_ms=1.0,
        transcript_path="runs/run_b/t1.t0.json",
    )

    listings = list_runs("toy", read_events=ledger.read)
    assert len(listings) == 1
    assert listings[0]["finished"] is False
    assert listings[0]["case_count"] == 2
    assert len(listings[0]["cases"]) == 1


def test_a_case_that_hit_drift_is_flagged(ledger):
    ledger.emit(
        "run_started",
        agent_id="toy",
        agent_version=0,
        run_id="run_c",
        split="train",
        case_count=1,
        trials=1,
    )
    ledger.emit(
        "case_result",
        agent_id="toy",
        agent_version=0,
        run_id="run_c",
        case_id="t1",
        trial=0,
        passed=False,
        score=0.0,
        cost_usd=0.0,
        latency_ms=1.0,
        transcript_path="runs/run_c/t1.t0.json",
        drift_event_id=7,
    )
    listings = list_runs("toy", read_events=ledger.read)
    assert listings[0]["cases"][0]["drift"] is True


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
        ledger.emit(
            "run_finished",
            agent_id="toy",
            agent_version=0,
            run_id=run_id,
            split="train",
            trials=1,
            pass_at_1=1.0,
            pass_pow_k=1.0,
            pass_rate_std=0.0,
            pass_rate_min=1.0,
            pass_rate_max=1.0,
            total_cost_usd=0.0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            drift_count=0,
            tokens_saved_by_drift=0,
        )
    listings = list_runs("toy", read_events=ledger.read)
    assert [listing["run_id"] for listing in listings] == ["run_2", "run_1"]


def test_start_run_runs_the_real_eval_and_reports_a_job(
    toy_package, evaluator_path, ledger, tmp_path
):
    def always_answers_billing(messages, model, tools=None):
        return {
            "text": '{"category": "billing", "priority": "p1"}',
            "tool_calls": [],
            "usage": {"tokens_in": 5, "tokens_out": 5},
            "cost_usd": 0.0,
        }

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(tmp_path / "jobs.sqlite3")
        connection.row_factory = sqlite3.Row
        return connection

    store = JobStore(connection_factory=connect, ensure_schema=True)
    job_id = start_run(
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

    for _ in range(200):
        job = store.get(job_id)
        if job.status in (STATUS_DONE, STATUS_FAILED):
            break
        time.sleep(0.01)
    assert job.status == STATUS_DONE
    assert job.progress == 1.0
    assert job.result["split"] == "train"
    assert "pass_at_1" in job.result
    assert ledger.of_kind("run_finished")
