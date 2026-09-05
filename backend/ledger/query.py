"""Read-only query layer over the append-only ``events`` table.

Everything in :mod:`backend.ledger.metrics` and :mod:`backend.ledger.api` reads
through this module.  Nothing here writes: the ledger is append-only and only
``backend.ledger.emit.emit`` may insert.

The table shape is PLAN.md section 4.1 (``contracts/events.py`` owns the payload
models).  ``Event`` below is the *row* view -- id/ts/kind/columns plus the
decoded JSON payload -- not a payload model.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Event",
    "Run",
    "agent_row",
    "agent_rows",
    "case_results",
    "events",
    "issue_status",
    "latest_run",
    "runs",
]

_EVENT_COLUMNS = "id, ts, kind, agent_id, agent_version, run_id, lever, payload"


@dataclass(frozen=True)
class Event:
    """One row of the ``events`` table with its payload already decoded."""

    id: int
    ts: str
    kind: str
    agent_id: str | None
    agent_version: int | None
    run_id: str | None
    lever: str | None
    payload: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Payload lookup shorthand."""
        return self.payload.get(key, default)

    def trial(self) -> int | None:
        """The ``case_result``'s trial index.

        Canonical field is ``trial``; ``repeat`` is accepted as an alias for
        events written before the addendum renamed it (PLAN_ADDENDUM.md sec A).
        """
        value = self.payload.get("trial", self.payload.get("repeat"))
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Run:
    """A ``run_started`` event and, when present, its ``run_finished`` partner."""

    run_id: str
    agent_id: str | None
    version: int | None
    split: str | None
    trials: int | None
    case_count: int | None
    started: Event
    finished: Event | None

    @property
    def is_finished(self) -> bool:
        return self.finished is not None


def _decode(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _row_to_event(row: Sequence[Any]) -> Event:
    return Event(
        id=row[0],
        ts=row[1],
        kind=row[2],
        agent_id=row[3],
        agent_version=row[4],
        run_id=row[5],
        lever=row[6],
        payload=_decode(row[7]),
    )


def events(
    conn: sqlite3.Connection,
    *,
    kind: str | Iterable[str] | None = None,
    agent_id: str | None = None,
    agent_version: int | None = None,
    run_id: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[Event]:
    """Return matching events, oldest first, payloads decoded.

    ``kind`` accepts a single kind or an iterable of kinds. ``since`` is an
    ISO8601 UTC timestamp compared lexicographically against ``ts`` (inclusive).
    """
    where: list[str] = []
    params: list[Any] = []

    if kind is not None:
        kinds = [kind] if isinstance(kind, str) else list(kind)
        if not kinds:
            return []
        placeholders = ",".join("?" for _ in kinds)
        where.append(f"kind IN ({placeholders})")
        params.extend(kinds)
    if agent_id is not None:
        where.append("agent_id = ?")
        params.append(agent_id)
    if agent_version is not None:
        where.append("agent_version = ?")
        params.append(agent_version)
    if run_id is not None:
        where.append("run_id = ?")
        params.append(run_id)
    if since is not None:
        where.append("ts >= ?")
        params.append(since)

    sql = "SELECT " + _EVENT_COLUMNS + " FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]


def runs(
    conn: sqlite3.Connection,
    agent_id: str,
    *,
    version: int | None = None,
    split: str | None = None,
    finished_only: bool = True,
) -> list[Run]:
    """Every run of ``agent_id``, oldest first.

    A run is a ``run_started`` event plus the ``run_finished`` event carrying the
    same ``run_id``. With ``finished_only`` (the default) unfinished runs are
    dropped, because metrics never report a run that has not completed.
    """
    started = events(conn, kind="run_started", agent_id=agent_id, agent_version=version)
    finished_by_run = {
        e.run_id: e
        for e in events(
            conn, kind="run_finished", agent_id=agent_id, agent_version=version
        )
        if e.run_id
    }

    out: list[Run] = []
    for event in started:
        if not event.run_id:
            continue
        run_split = event.get("split")
        if split is not None and run_split != split:
            continue
        finished = finished_by_run.get(event.run_id)
        if finished_only and finished is None:
            continue
        out.append(
            Run(
                run_id=event.run_id,
                agent_id=event.agent_id,
                version=event.agent_version,
                split=run_split,
                trials=event.get("trials", event.get("repeats")),
                case_count=event.get("case_count"),
                started=event,
                finished=finished,
            )
        )
    return out


def latest_run(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    split: str,
    *,
    finished_only: bool = True,
) -> Run | None:
    """The most recent run of ``(agent_id, version, split)``, or None."""
    candidates = runs(
        conn, agent_id, version=version, split=split, finished_only=finished_only
    )
    return candidates[-1] if candidates else None


def case_results(conn: sqlite3.Connection, run_id: str) -> list[Event]:
    """All ``case_result`` events for one run, oldest first."""
    return events(conn, kind="case_result", run_id=run_id)


def agent_row(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    """The ``agents`` row as a dict, or None when absent/table missing."""
    try:
        row = conn.execute(
            "SELECT agent_id, goal, domain, evaluator_id, current_version, created_ts "
            "FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return {
        "agent_id": row[0],
        "goal": row[1],
        "domain": row[2],
        "evaluator_id": row[3],
        "current_version": row[4],
        "created_ts": row[5],
    }


def agent_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every ``agents`` row as a dict; empty when the table is missing."""
    try:
        rows = conn.execute(
            "SELECT agent_id, goal, domain, evaluator_id, current_version, created_ts "
            "FROM agents ORDER BY created_ts ASC, agent_id ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "agent_id": r[0],
            "goal": r[1],
            "domain": r[2],
            "evaluator_id": r[3],
            "current_version": r[4],
            "created_ts": r[5],
        }
        for r in rows
    ]


def issue_status(
    conn: sqlite3.Connection, issue_ids: Iterable[str]
) -> dict[str, str | None]:
    """Map issue id -> status from the ``issues`` table.

    Ids with no row (or no table yet) map to ``None`` so callers decide how to
    treat an unknown status rather than having one invented for them.
    """
    ids = [str(i) for i in issue_ids]
    out: dict[str, str | None] = {i: None for i in ids}
    if not ids:
        return out
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = conn.execute(
            "SELECT id, status FROM issues WHERE id IN (" + placeholders + ")",
            ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for issue_id, status in rows:
        out[str(issue_id)] = status
    return out
