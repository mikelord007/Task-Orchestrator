"""Plain-function handlers behind ``POST /agents/{id}/run`` and
``GET /agents/{id}/runs``.

Kept separate from any web framework so they can be unit tested now and wired
into ``backend/app.py`` as one-line route bodies once Phase 0 lands:

    @app.post("/agents/{agent_id}/run")
    def run_agent(agent_id: str, body: RunRequest):
        return {"run_id_job": start_run(agent_id, body.split)}

    @app.get("/jobs/{job_id}")
    def get_job_status(job_id: str):
        return jobs.default_store.get(job_id)

    @app.get("/agents/{agent_id}/runs")
    def get_runs(agent_id: str):
        return list_runs(agent_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.runtime.evaluation import DEFAULT_RUNS_DIR, LoadedPackage, run_eval
from backend.runtime.events import EmitFn, ReadEventsFn, default_read_events
from backend.runtime.jobs import JobStore, default_store, run_in_background
from backend.runtime.loop import CompleteFn
from backend.runtime.package import DEFAULT_AGENTS_DIR
from backend.runtime.scoring import DEFAULT_EVALUATORS_DIR


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
    """Start ``run_eval`` on a background thread; return its job id.

    Job progress tracks cases done / total (``run_eval``'s ``progress``
    callback); the job's result is the run summary on success. The keyword
    overrides below exist for tests - the FastAPI route calls this with just
    ``(agent_id, split)`` and lets ``run_eval`` resolve everything from disk,
    ``backend.llm`` and the real ledger.
    """
    store = store or default_store

    def work(progress):
        summary = run_eval(
            agent_id,
            split=split,
            trials=trials,
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

    return run_in_background(store, "run", agent_id, work)


@dataclass
class CaseRow:
    """One row of the per-run case table (PLAN_ADDENDUM.md section A)."""

    case_id: str
    passed_by_trial: list[bool]
    score: float
    cost_usd: float
    latency_ms: float
    transcript_paths: list[str]
    drift: bool
    trace_url: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed_by_trial": self.passed_by_trial,
            "score": round(self.score, 6),
            "cost_usd": round(self.cost_usd, 8),
            "latency_ms": round(self.latency_ms, 2),
            "transcript_paths": self.transcript_paths,
            "drift": self.drift,
            "trace_url": self.trace_url,
        }


@dataclass
class RunListing:
    run_id: str
    split: str
    trials: int
    case_count: int
    finished: dict[str, Any] | None = None
    cases: list[CaseRow] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "split": self.split,
            "trials": self.trials,
            "case_count": self.case_count,
            **(self.finished or {}),
            "finished": self.finished is not None,
            "cases": [c.payload() for c in self.cases],
        }


def list_runs(
    agent_id: str, *, read_events: ReadEventsFn | None = None
) -> list[dict[str, Any]]:
    """``run_finished`` summaries with per-task rows, newest first.

    A run that has ``run_started`` but no ``run_finished`` yet (still running,
    or crashed) is reported with whatever ``case_result`` rows exist so far and
    ``finished: null``.
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

    by_run: dict[str, list[dict[str, Any]]] = {}
    for row in read_events(agent_id=agent_id, kind="case_result"):
        run_id = row.get("run_id")
        if run_id:
            by_run.setdefault(run_id, []).append(row.get("payload") or {})

    listings: list[RunListing] = []
    run_ids = set(started) | set(finished) | set(by_run)
    for run_id in run_ids:
        start_payload = (started.get(run_id) or {}).get("payload") or {}
        finish_row = finished.get(run_id)
        finish_payload = dict(finish_row["payload"]) if finish_row else None
        split = (
            start_payload.get("split") or (finish_payload or {}).get("split") or "train"
        )
        trials = (
            start_payload.get("trials") or (finish_payload or {}).get("trials") or 0
        )
        case_count = start_payload.get("case_count") or 0

        by_case: dict[str, list[dict[str, Any]]] = {}
        for payload in by_run.get(run_id, []):
            case_id = str(payload.get("case_id"))
            by_case.setdefault(case_id, []).append(payload)

        cases: list[CaseRow] = []
        for case_id in sorted(by_case):
            rows = sorted(
                by_case[case_id], key=lambda p: p.get("trial", p.get("repeat", 0))
            )
            scores = [float(r.get("score") or 0.0) for r in rows]
            costs = [float(r.get("cost_usd") or 0.0) for r in rows]
            latencies = [float(r.get("latency_ms") or 0.0) for r in rows]
            trace_url = next(
                (r.get("trace_url") for r in rows if r.get("trace_url")), None
            )
            cases.append(
                CaseRow(
                    case_id=case_id,
                    passed_by_trial=[bool(r.get("passed")) for r in rows],
                    score=sum(scores) / len(scores) if scores else 0.0,
                    cost_usd=sum(costs),
                    latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
                    transcript_paths=[str(r.get("transcript_path")) for r in rows],
                    drift=any(r.get("drift_event_id") is not None for r in rows),
                    trace_url=trace_url,
                )
            )

        listings.append(
            RunListing(
                run_id=run_id,
                split=split,
                trials=int(trials),
                case_count=int(case_count) or len(cases),
                finished=finish_payload,
                cases=cases,
            )
        )

    def sort_key(listing: RunListing) -> Any:
        finish_row = finished.get(listing.run_id)
        start_row = started.get(listing.run_id)
        return (finish_row or start_row or {}).get("id", 0)

    listings.sort(key=sort_key, reverse=True)
    return [listing.payload() for listing in listings]
