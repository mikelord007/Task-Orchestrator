"""Thin adapters over the ledger.

Writes go through ``backend/ledger/emit.py`` only - append-only, validated,
never updated or deleted. Reads here are raw event reads used by the memory
demotion pass; every *derived* metric belongs to W1's ``metrics.py``.

Both the emitter and the reader are injectable so tests never touch the DB.
"""

from __future__ import annotations

import json
from typing import Any, Callable

EmitFn = Callable[..., Any]
ReadEventsFn = Callable[..., list[dict[str, Any]]]


def default_emit(kind: str, /, **fields: Any) -> Any:
    """``kind`` is positional-only: several payloads (e.g. ``drift_detected``)
    carry their own ``kind`` field, which would otherwise collide with this
    one's keyword name."""
    from backend.ledger.emit import emit

    return emit(kind, **fields)


def event_id_of(emitted: Any) -> int | None:
    """Best-effort event id from whatever ``emit`` returned."""
    if isinstance(emitted, int):
        return emitted
    if isinstance(emitted, dict):
        value = emitted.get("id")
        return int(value) if isinstance(value, int) else None
    value = getattr(emitted, "id", None)
    return int(value) if isinstance(value, int) else None


def _connect() -> Any:
    from backend import db

    for name in ("connect", "get_connection", "connection"):
        factory = getattr(db, name, None)
        if callable(factory):
            return factory()
    raise RuntimeError("backend.db exposes no connection factory")


def default_read_events(
    agent_id: str | None = None, kind: str | None = None
) -> list[dict[str, Any]]:
    """Raw event rows with ``payload`` already decoded."""
    sql = "SELECT id, ts, kind, agent_id, agent_version, run_id, lever, payload FROM events"
    clauses: list[str] = []
    params: list[Any] = []
    if agent_id is not None:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id ASC"
    connection = _connect()
    try:
        rows = connection.execute(sql, params).fetchall()
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
    out: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row) if not isinstance(row, dict) else dict(row)
        payload = record.get("payload")
        if isinstance(payload, str):
            try:
                record["payload"] = json.loads(payload)
            except json.JSONDecodeError:
                record["payload"] = {}
        out.append(record)
    return out
