"""Background-job helper over the ``improve_jobs`` table (migration 0001).

A tiny wrapper so ``POST /agents/{id}/run`` and (later) W6's
``POST /agents/{id}/improve`` can hand work to a background thread and let the
frontend poll ``GET /jobs/{job_id}`` for progress, without either endpoint
touching sqlite directly.

Schema (``backend/migrations/0001_init.sql``)::

    improve_jobs(job_id, agent_id, kind, status, attempts, max_attempts,
                 issue_id, current_step, result, error, created_ts, updated_ts)

``status`` is one of ``queued | running | done | error``. There is no numeric
progress column, so ``current_step`` (TEXT) holds a small JSON object,
``{"label": str, "done": int, "total": int}`` - :meth:`Job.progress` reads
``done``/``total`` back out in the ``{done, total}`` shape the frontend
(``frontend/lib/types.ts``) expects from ``GET /jobs/{id}``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db import init_db, utcnow

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

INTERRUPTED_ERROR = "Interrupted: backend restarted before this job completed"

ConnectionFactory = Callable[[], Any]


def mark_incomplete_jobs_interrupted(connection: Any) -> int:
    """Mark work a prior process left behind as terminally interrupted.

    Jobs execute on in-process daemon threads, so they cannot survive a
    process or VM restart. Recording that fact on the next startup avoids
    leaving clients polling ``queued``/``running`` forever. The production
    deployment intentionally runs one application process; running multiple
    processes against this store would make startup ownership ambiguous.
    """
    now = utcnow()
    with connection:
        cursor = connection.execute(
            "UPDATE improve_jobs SET status = ?, error = ?, updated_ts = ? WHERE status IN (?, ?)",
            (STATUS_ERROR, INTERRUPTED_ERROR, now, STATUS_QUEUED, STATUS_RUNNING),
        )
    return int(cursor.rowcount)


def default_connection_factory(db: str | Path | None = None) -> ConnectionFactory:
    """A factory opening a fresh, migrated connection to ``db`` (or the
    default db) each call. ``init_db`` (not ``connect``) so the schema is
    guaranteed to exist even if ``backend.app``'s startup migration has not
    run yet (e.g. a script using this module directly)."""

    def factory() -> Any:
        return init_db(db)

    return factory


@dataclass
class Job:
    job_id: str
    agent_id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    issue_id: str | None
    current_step: str | None
    result: Any
    error: str | None
    created_ts: str
    updated_ts: str

    @classmethod
    def from_row(cls, row: Any) -> Job:
        raw_result = row["result"]
        return cls(
            job_id=row["job_id"],
            agent_id=row["agent_id"],
            kind=row["kind"],
            status=row["status"],
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or 3),
            issue_id=row["issue_id"],
            current_step=row["current_step"],
            result=json.loads(raw_result) if raw_result else None,
            error=row["error"],
            created_ts=row["created_ts"],
            updated_ts=row["updated_ts"],
        )

    def _step(self) -> dict[str, Any]:
        if not self.current_step:
            return {}
        try:
            parsed = json.loads(self.current_step)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def progress(self) -> dict[str, int]:
        """``{done, total}`` (``frontend/lib/types.ts`` ``Job.progress``)."""
        step = self._step()
        return {"done": int(step.get("done") or 0), "total": int(step.get("total") or 0)}

    def step_label(self) -> str | None:
        """Human-readable step name, when one was set (e.g. a future
        ``improve`` job's "diagnosing"/"patching"/"gating")."""
        label = self._step().get("label")
        return str(label) if label else None

    def payload(self) -> dict[str, Any]:
        """``GET /jobs/{id}`` response body."""
        return {
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress(),
            "step_label": self.step_label(),
            "result": self.result,
            "error": self.error,
        }


class JobStore:
    """Thin, injectable wrapper over ``improve_jobs``.

    ``connection_factory`` is called fresh for every operation (matching how
    ``backend.db.connect`` is meant to be used) so this is safe to share
    across the background thread and the request thread.
    """

    def __init__(self, connection_factory: ConnectionFactory | None = None) -> None:
        self._connection_factory = connection_factory or default_connection_factory()

    def _connect(self) -> Any:
        return self._connection_factory()

    def create(
        self,
        agent_id: str,
        kind: str = "run",
        *,
        job_id: str | None = None,
        issue_id: str | None = None,
        max_attempts: int = 3,
    ) -> str:
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        now = utcnow()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO improve_jobs "
                    "(job_id, agent_id, kind, status, attempts, max_attempts, issue_id, "
                    " current_step, result, error, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, ?, ?)",
                    (job_id, agent_id, kind, STATUS_QUEUED, max_attempts, issue_id, now, now),
                )
        finally:
            connection.close()
        return job_id

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        attempts: int | None = None,
        current_step: str | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if attempts is not None:
            sets.append("attempts = ?")
            params.append(attempts)
        if current_step is not None:
            sets.append("current_step = ?")
            params.append(current_step)
        if result is not None:
            sets.append("result = ?")
            params.append(json.dumps(result, default=str))
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        sets.append("updated_ts = ?")
        params.append(utcnow())
        params.append(job_id)
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    f"UPDATE improve_jobs SET {', '.join(sets)} WHERE job_id = ?", params
                )
        finally:
            connection.close()

    def get(self, job_id: str) -> Job | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM improve_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        finally:
            connection.close()
        return Job.from_row(row) if row is not None else None

    @staticmethod
    def _encode_step(label: str, done: int = 0, total: int = 0) -> str:
        return json.dumps({"label": label, "done": done, "total": total})

    def mark_running(self, job_id: str) -> None:
        self.update(job_id, status=STATUS_RUNNING, current_step=self._encode_step("starting"))

    def mark_progress(self, job_id: str, done: int, total: int) -> None:
        self.update(job_id, current_step=self._encode_step(f"{done}/{total} cases", done, total))

    def mark_done(self, job_id: str, result: Any) -> None:
        # Keep whatever done/total mark_progress last reported (a completed
        # run's last progress call already reports done == total).
        job = self.get(job_id)
        progress = job.progress() if job is not None else {"done": 0, "total": 0}
        self.update(
            job_id,
            status=STATUS_DONE,
            current_step=self._encode_step("done", progress["done"], progress["total"]),
            result=result if result is not None else {},
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self.get(job_id)
        progress = job.progress() if job is not None else {"done": 0, "total": 0}
        self.update(
            job_id,
            status=STATUS_ERROR,
            current_step=self._encode_step("error", progress["done"], progress["total"]),
            error=error,
        )


default_store = JobStore()


def run_in_background(
    store: JobStore,
    kind: str,
    agent_id: str,
    work: Callable[[Callable[[int, int], None]], Any],
    *,
    job_id: str | None = None,
) -> str:
    """Create a job, run ``work`` on a daemon thread, and report its outcome.

    ``work`` receives a ``progress(done, total)`` callback it should call as it
    makes progress; the return value becomes the job's result on success. Pass
    ``job_id`` to reuse an id already handed to the caller (e.g. the run id
    ``POST /agents/{id}/run`` returns) instead of minting a fresh one.
    """
    import threading

    from backend.demo_limits import claim_workflow_slot
    from backend.runtime import neatlogs

    slot = claim_workflow_slot()
    try:
        job_id = store.create(agent_id, kind, job_id=job_id)
    except Exception:
        slot.release()
        raise
    parent_context = neatlogs.copy_current_context()

    def target() -> None:
        try:
            with neatlogs.workflow_span(
                "task_orchestrator.job",
                job_id=neatlogs.safe_identifier(job_id, "job"),
                agent_id=neatlogs.safe_identifier(agent_id, "agent"),
                job_kind=kind if kind in {"run", "improve"} else "other",
            ):
                store.mark_running(job_id)
                try:
                    result = work(lambda done, total: store.mark_progress(job_id, done, total))
                except Exception as exc:  # noqa: BLE001 - report job failures
                    store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
                    return
                store.mark_done(job_id, result)
        finally:
            slot.release()

    threading.Thread(target=lambda: parent_context.run(target), daemon=True).start()
    return job_id
