"""Background-job helper over the ``improve_jobs`` table.

A tiny wrapper so ``POST /agents/{id}/run`` and (later) W6's
``POST /agents/{id}/improve`` can hand work to a background thread and let the
frontend poll ``GET /jobs/{job_id}`` for progress, without either endpoint
touching sqlite directly.

The connection is injectable (see :func:`default_connection`) so tests never
touch the real database; the default reaches for ``backend.db`` once Phase 0
lands. Schema (created by W0's migrations):

``improve_jobs(job_id TEXT PRIMARY KEY, kind TEXT, agent_id TEXT, status TEXT,
progress REAL, result TEXT, error TEXT, created_ts TEXT, updated_ts TEXT)``
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

ConnectionFn = Callable[[], sqlite3.Connection]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS improve_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    agent_id TEXT,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    result TEXT,
    error TEXT,
    created_ts TEXT NOT NULL,
    updated_ts TEXT NOT NULL
)
"""


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def default_connection() -> sqlite3.Connection:
    from backend import db

    for name in ("connect", "get_connection", "connection"):
        factory = getattr(db, name, None)
        if callable(factory):
            connection = factory()
            connection.row_factory = sqlite3.Row
            return connection
    raise RuntimeError("backend.db exposes no connection factory")


@dataclass
class Job:
    job_id: str
    kind: str
    agent_id: str | None
    status: str
    progress: float
    result: Any
    error: str | None
    created_ts: str
    updated_ts: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Job:
        raw_result = row["result"]
        result = json.loads(raw_result) if raw_result else None
        return cls(
            job_id=row["job_id"],
            kind=row["kind"],
            agent_id=row["agent_id"],
            status=row["status"],
            progress=float(row["progress"] or 0.0),
            result=result,
            error=row["error"],
            created_ts=row["created_ts"],
            updated_ts=row["updated_ts"],
        )


class JobStore:
    """Thin, injectable wrapper over ``improve_jobs``."""

    def __init__(
        self,
        connection_factory: ConnectionFn = default_connection,
        ensure_schema: bool = False,
    ) -> None:
        self._connection_factory = connection_factory
        self._ensure_schema = ensure_schema

    def _connect(self) -> sqlite3.Connection:
        connection = self._connection_factory()
        if self._ensure_schema:
            connection.execute(_SCHEMA)
        return connection

    def create(self, kind: str, agent_id: str | None = None) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = _now()
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO improve_jobs "
                "(job_id, kind, agent_id, status, progress, result, error, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, 0, NULL, NULL, ?, ?)",
                (job_id, kind, agent_id, STATUS_PENDING, now, now),
            )
            connection.commit()
        finally:
            connection.close()
        return job_id

    def update(
        self,
        job_id: str,
        status: str | None = None,
        progress: float | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if progress is not None:
            sets.append("progress = ?")
            params.append(float(progress))
        if result is not None:
            sets.append("result = ?")
            params.append(json.dumps(result, default=str))
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        sets.append("updated_ts = ?")
        params.append(_now())
        params.append(job_id)
        connection = self._connect()
        try:
            connection.execute(
                f"UPDATE improve_jobs SET {', '.join(sets)} WHERE job_id = ?", params
            )
            connection.commit()
        finally:
            connection.close()

    def get(self, job_id: str) -> Job | None:
        connection = self._connect()
        try:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM improve_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        finally:
            connection.close()
        return Job.from_row(row) if row is not None else None

    def mark_running(self, job_id: str) -> None:
        self.update(job_id, status=STATUS_RUNNING, progress=0.0)

    def mark_progress(self, job_id: str, done: int, total: int) -> None:
        fraction = (done / total) if total else 1.0
        self.update(job_id, progress=round(fraction, 4))

    def mark_done(self, job_id: str, result: Any) -> None:
        self.update(
            job_id,
            status=STATUS_DONE,
            progress=1.0,
            result=result if result is not None else {},
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self.update(job_id, status=STATUS_FAILED, error=error)


default_store = JobStore()


def run_in_background(
    store: JobStore,
    kind: str,
    agent_id: str,
    work: Callable[[Callable[[int, int], None]], Any],
) -> str:
    """Create a job, run ``work`` on a daemon thread, and report its outcome.

    ``work`` receives a ``progress(done, total)`` callback it should call as it
    makes progress; the return value becomes the job's result on success.
    """
    import threading

    job_id = store.create(kind, agent_id)

    def target() -> None:
        store.mark_running(job_id)
        try:
            result = work(lambda done, total: store.mark_progress(job_id, done, total))
        except Exception as exc:  # noqa: BLE001 - a failed job is reported, not raised
            store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
            return
        store.mark_done(job_id, result)

    threading.Thread(target=target, daemon=True).start()
    return job_id
