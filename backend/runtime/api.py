"""``POST /agents/{id}/run``, ``GET /agents/{id}/runs``, ``GET /jobs/{job_id}``
(contracts/api.md).

The route bodies are one line each; the actual logic (``start_run``,
``list_runs``) is plain functions so they are unit-testable without spinning
up FastAPI or touching the real ledger/db.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.runtime.evaluation import DEFAULT_RUNS_DIR, LoadedPackage, run_eval
from backend.runtime.events import EmitFn, ReadEventsFn, default_read_events
from backend.runtime.jobs import JobStore, default_store, run_in_background
from backend.runtime.loop import CompleteFn
from backend.runtime.package import DEFAULT_AGENTS_DIR
from backend.runtime.scoring import DEFAULT_EVALUATORS_DIR

router = APIRouter()


def start_run(
    agent_id: str,
    split: str = "train",
    *,
    trials: int | None = None,
    store: JobStore | None = None,
    agents_dir: Path | str = DEFAULT_AGENTS_DIR,
    evaluators_dir: Path | str = DEFAULT_EVALUATORS_DIR,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
    package: LoadedPackage | None = None,
    evaluator_path: Path | str | None = None,
    complete: CompleteFn | None = None,
    emit: EmitFn | None = None,
    read_events: ReadEventsFn | None = None,
) -> str:
    """Generate the run id, start ``run_eval`` on it in the background, and
    return the run id immediately (``POST /agents/{id}/run`` -> ``{run_id}``,
    per contracts/api.md - the run id is known upfront, unlike a job id).

    Progress (cases done / total) is tracked in ``improve_jobs`` under a job
    whose id equals the run id, so ``GET /jobs/{run_id}`` also works. The
    keyword overrides below exist for tests; the FastAPI route calls this with
    just ``(agent_id, split)`` and lets ``run_eval`` resolve everything else
    from disk, ``backend.llm`` and the real ledger.
    """
    run_id = f"run_{uuid4().hex[:12]}"
    store = store or default_store

    def work(progress):
        summary = run_eval(
            agent_id,
            split=split,
            trials=trials,
            run_id=run_id,
            agents_dir=agents_dir,
            evaluators_dir=evaluators_dir,
            runs_dir=runs_dir,
            package=package,
            evaluator_path=evaluator_path,
            complete=complete,
            emit=emit,
            read_events=read_events,
            progress=progress,
        )
        return {"run_id": summary.run_id, **summary.finished_payload()}

    run_in_background(store, "run", agent_id, work, job_id=run_id)
    return run_id


@dataclass
class TaskResult:
    """One row of ``RunSummary.tasks`` (contracts/api.md).

    Every field except ``passed_by_trial`` is taken from trial 0 of this run -
    enough for one representative transcript per row without inflating the
    payload with ``trials`` copies; the per-trial pass/fail strip is the part
    that must show every trial.
    """

    case_id: str
    passed_by_trial: list[bool]
    score: float
    cost_usd: float
    latency_ms: int
    tool_calls: int
    tool_errors: int
    rules_injected: list[str]
    transcript_path: str | None
    trace_url: str | None
    drift_kind: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed_by_trial": self.passed_by_trial,
            "score": self.score,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "rules_injected": self.rules_injected,
            "transcript_path": self.transcript_path,
            "trace_url": self.trace_url,
            "drift_kind": self.drift_kind,
        }


def _drift_kinds_by_event_id(read_events: ReadEventsFn, agent_id: str) -> dict[int, str]:
    return {
        row["id"]: row["payload"]["kind"]
        for row in read_events(agent_id=agent_id, kind="drift_detected")
        if row.get("id") is not None
    }


def list_runs(agent_id: str, *, read_events: ReadEventsFn | None = None) -> list[dict[str, Any]]:
    """``[RunSummary]`` (contracts/api.md), newest first.

    A run that has ``run_started`` but no ``run_finished`` yet (still running,
    or crashed) is reported with whatever ``case_result`` rows exist so far and
    ``finished_ts: null``.
    """
    read_events = read_events or default_read_events

    started = {
        row["run_id"]: row
        for row in read_events(agent_id=agent_id, kind="run_started")
        if row.get("run_id")
    }
    finished = {
        row["run_id"]: row
        for row in read_events(agent_id=agent_id, kind="run_finished")
        if row.get("run_id")
    }
    drift_kind_of = _drift_kinds_by_event_id(read_events, agent_id)

    by_run: dict[str, list[dict[str, Any]]] = {}
    agent_version_of: dict[str, int] = {}
    for row in read_events(agent_id=agent_id, kind="case_result"):
        run_id = row.get("run_id")
        if not run_id:
            continue
        by_run.setdefault(run_id, []).append(row.get("payload") or {})
        if row.get("agent_version") is not None:
            agent_version_of[run_id] = row["agent_version"]

    summaries: list[dict[str, Any]] = []
    for run_id in set(started) | set(finished) | set(by_run):
        start_row = started.get(run_id)
        finish_row = finished.get(run_id)
        start_payload = (start_row or {}).get("payload") or {}
        finish_payload = (finish_row or {}).get("payload") or {}
        version = (
            (start_row or {}).get("agent_version")
            or (finish_row or {}).get("agent_version")
            or agent_version_of.get(run_id)
            or 0
        )
        split = start_payload.get("split") or finish_payload.get("split") or "train"
        trials = int(start_payload.get("trials") or finish_payload.get("trials") or 0)

        by_case: dict[str, list[dict[str, Any]]] = {}
        for payload in by_run.get(run_id, []):
            by_case.setdefault(str(payload.get("case_id")), []).append(payload)

        tasks: list[TaskResult] = []
        for case_id in sorted(by_case):
            rows = sorted(by_case[case_id], key=lambda p: p.get("trial", p.get("repeat", 0)))
            first = rows[0]
            drift_event_id = first.get("drift_event_id")
            tasks.append(
                TaskResult(
                    case_id=case_id,
                    passed_by_trial=[bool(r.get("passed")) for r in rows],
                    score=float(first.get("score") or 0.0),
                    cost_usd=float(first.get("cost_usd") or 0.0),
                    latency_ms=int(first.get("latency_ms") or 0),
                    tool_calls=int(first.get("tool_calls") or 0),
                    tool_errors=int(first.get("tool_errors") or 0),
                    rules_injected=list(first.get("rules_injected") or []),
                    transcript_path=first.get("transcript_path"),
                    trace_url=first.get("trace_url"),
                    drift_kind=drift_kind_of.get(drift_event_id)
                    if drift_event_id is not None
                    else None,
                )
            )

        summaries.append(
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "version": int(version),
                "split": split,
                "trials": trials,
                "started_ts": (start_row or finish_row or {}).get("ts"),
                "finished_ts": (finish_row or {}).get("ts"),
                "pass_at_1": finish_payload.get("pass_at_1"),
                "pass_pow_k": finish_payload.get("pass_pow_k"),
                "total_cost_usd": finish_payload.get("total_cost_usd"),
                "p50_latency_ms": finish_payload.get("p50_latency_ms"),
                "p95_latency_ms": finish_payload.get("p95_latency_ms"),
                "drift_count": finish_payload.get("drift_count"),
                "tasks": [t.payload() for t in tasks],
                "_sort_id": (finish_row or start_row or {}).get("id", 0),
            }
        )

    summaries.sort(key=lambda s: s.pop("_sort_id"), reverse=True)
    return summaries


# -- routes ---------------------------------------------------------------


VALID_SPLITS = ("train", "holdout")


class RunRequest(BaseModel):
    split: str = "train"


@router.post("/agents/{agent_id}/run")
def post_agent_run(agent_id: str, body: RunRequest) -> dict[str, str]:
    if body.split not in VALID_SPLITS:
        raise HTTPException(
            status_code=422, detail=f"split must be one of {VALID_SPLITS}, got {body.split!r}"
        )
    from backend.runtime.store import resolve_agent

    if not resolve_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"no such agent: {agent_id}")
    return {"run_id": start_run(agent_id, body.split)}


@router.get("/agents/{agent_id}/runs")
def get_agent_runs(agent_id: str) -> list[dict[str, Any]]:
    return list_runs(agent_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = default_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no such job: {job_id}")
    return job.payload()
