"""Append-only ledger writes (PLAN.md section 4.1, worker W0 stub for W1).

`emit()` validates the payload against `contracts/events.py` and INSERTs one
row. There is deliberately **no update and no delete** in this module: display
status is derived from the event stream, never stored (rule section 2.4).

W1 builds `metrics.py` and the fix-card assembly on top of `read()`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.db import init_db, utcnow
from contracts.events import EVENT_KINDS, PAYLOAD_MODELS, Lever, validate_payload

__all__ = ["emit", "read", "LedgerEvent", "EVENT_KINDS"]

LedgerEvent = dict[str, Any]

# Field names that exist on some payload models but would be confusing (or, in
# an earlier version of this function, outright impossible) to pass as a bare
# `emit(..., kind=..., lever=...)` keyword: `kind` is a field on
# drift_detected/memory_written, and `lever` is both a payload field
# (fix_proposed, lesson_recorded) and this function's own column parameter.
# Force those two through `payload={...}` so a reader is never left guessing
# which "kind" or "lever" a call site means.
_AMBIGUOUS_PAYLOAD_KEYS = ("kind", "lever")


def _resolve_conn(
    conn: sqlite3.Connection | None, db: str | Path | None
) -> tuple[sqlite3.Connection, bool]:
    if conn is not None:
        return conn, False
    return init_db(db), True


def _normalize_lever(lever: Any, payload: dict[str, Any]) -> str | None:
    """Column `lever` mirrors the payload's lever when the caller omits it."""
    if lever is None:
        lever = payload.get("lever")
    if lever is None:
        return None
    if isinstance(lever, Lever):
        return lever.value
    return Lever(lever).value


def emit(
    event_kind: str,
    agent_id: str | None = None,
    agent_version: int | None = None,
    run_id: str | None = None,
    lever: str | Lever | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    ts: str | None = None,
    payload: dict[str, Any] | None = None,
    **fields: Any,
) -> int:
    """Validate and append one event. Returns the new row id.

    Payload keys are passed as keyword arguments::

        emit("run_started", agent_id="a1", run_id="r_1",
             split="train", case_count=42, trials=3)

    `kind` and `lever` are payload field names on some event kinds
    (`drift_detected.kind`, `fix_proposed.lever`, ...). Passing either as a
    bare keyword argument is rejected with a clear error -- use the explicit
    `payload=` dict instead::

        emit("drift_detected", agent_id="a1",
             payload={"kind": "loop", "case_id": "c1", ...})

    `lever=` (the ledger column, distinct from any payload field of the same
    name) is the one exception: when the event's model has a `lever` field,
    the column value is copied into the payload automatically.

    Raises `KeyError` for an unknown kind, `TypeError` for an ambiguous bare
    keyword, and `pydantic.ValidationError` when the payload does not satisfy
    the contract -- in every case nothing is written.
    """
    model = PAYLOAD_MODELS.get(event_kind)
    if model is not None:
        for key in _AMBIGUOUS_PAYLOAD_KEYS:
            if key in fields and key in model.model_fields:
                raise TypeError(
                    f"emit({event_kind!r}, ..., {key}=...) is ambiguous: {key!r} is a "
                    f"payload field on this event. Pass it inside payload={{...}} instead: "
                    f"emit({event_kind!r}, ..., payload={{{key!r}: ...}})"
                )

    body: dict[str, Any] = {**(payload or {}), **fields}
    if lever is not None and model is not None and "lever" in model.model_fields:
        body.setdefault("lever", lever.value if isinstance(lever, Lever) else lever)

    validated = validate_payload(event_kind, body)
    lever_value = _normalize_lever(lever, validated)

    connection, owned = _resolve_conn(conn, db)
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO events (ts, kind, agent_id, agent_version, run_id, lever, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts or utcnow(),
                    event_kind,
                    agent_id,
                    agent_version,
                    run_id,
                    lever_value,
                    json.dumps(validated, sort_keys=True),
                ),
            )
        return int(cursor.lastrowid)
    finally:
        if owned:
            connection.close()


def read(
    kind: str | None = None,
    agent_id: str | None = None,
    since: str | int | None = None,
    *,
    run_id: str | None = None,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
) -> list[LedgerEvent]:
    """Read events oldest-first with the payload JSON already parsed.

    `since` is an event id (int, exclusive) or an ISO8601 timestamp
    (str, inclusive) -- the `GET /events?since=` query parameter accepts both.
    """
    where: list[str] = []
    params: list[Any] = []
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if agent_id is not None:
        where.append("agent_id = ?")
        params.append(agent_id)
    if run_id is not None:
        where.append("run_id = ?")
        params.append(run_id)
    if isinstance(since, int):
        where.append("id > ?")
        params.append(since)
    elif isinstance(since, str):
        where.append("ts >= ?")
        params.append(since)

    sql = "SELECT * FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    connection, owned = _resolve_conn(conn, db)
    try:
        rows = connection.execute(sql, params).fetchall()
    finally:
        if owned:
            connection.close()

    return [
        {
            "id": row["id"],
            "ts": row["ts"],
            "kind": row["kind"],
            "agent_id": row["agent_id"],
            "agent_version": row["agent_version"],
            "run_id": row["run_id"],
            "lever": row["lever"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]
