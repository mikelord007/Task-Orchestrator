"""FastAPI router for the ledger read endpoints (``contracts/api.md``).

Every handler is a read. The router owns no state and holds no cache: each
request recomputes from the ledger, so a chart can never disagree with the
events behind it.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from backend.ledger import metrics
from backend.ledger.query import Event, agent_row
from backend.ledger.query import events as query_events

router = APIRouter(tags=["ledger"])

# Connection factory names Phase 0's ``backend/db.py`` might expose. Resolved
# lazily so this module imports without a database present (tests override the
# dependency), and so the router does not pin one spelling of the scaffold.
_CONNECT_NAMES = ("connect", "get_connection", "connection", "open_db")


def _open_connection() -> sqlite3.Connection:
    from backend import db

    for name in _CONNECT_NAMES:
        factory = getattr(db, name, None)
        if callable(factory):
            return factory()
    raise RuntimeError(
        "backend.db exposes no connection factory; expected one of " + ", ".join(_CONNECT_NAMES)
    )


def get_connection() -> Iterator[sqlite3.Connection]:
    """Request-scoped sqlite connection. Overridden in tests."""
    conn = _open_connection()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_connection)]


def _event_dict(event: Event) -> dict[str, Any]:
    return dataclasses.asdict(event)


@router.get("/events")
def list_events(
    conn: Conn,
    agent_id: str | None = None,
    kind: str | None = None,
    run_id: str | None = None,
    since: str | None = None,
    limit: Annotated[int | None, Query(ge=1, le=10_000)] = None,
) -> list[dict[str, Any]]:
    """Raw ledger rows, oldest first, payloads decoded."""
    return [
        _event_dict(e)
        for e in query_events(
            conn, kind=kind, agent_id=agent_id, run_id=run_id, since=since, limit=limit
        )
    ]


# Registered before ``/insights/{agent_id}`` so "compare" is not read as an id.
@router.get("/insights/compare")
def insights_compare(conn: Conn) -> dict[str, Any]:
    """Per-domain series for every agent, plus ``reports/ablation.json`` if present."""
    return metrics.insights_compare(conn)


@router.get("/insights/{agent_id}")
def insights(agent_id: str, conn: Conn) -> dict[str, Any]:
    """Everything the insights page charts, computed from the ledger."""
    return metrics.insights(conn, agent_id)


@router.get("/agents/{agent_id}/fixes")
def fixes(agent_id: str, conn: Conn) -> list[dict[str, Any]]:
    """Fix cards for one agent, newest first."""
    return metrics.fix_cards(conn, agent_id)


@router.get("/agents/{agent_id}/fixes/{to_version}/diff", response_class=PlainTextResponse)
def fix_diff(agent_id: str, to_version: int, conn: Conn) -> PlainTextResponse:
    """The unified diff for a fix, as ``text/plain``."""
    diff = metrics.fix_diff(conn, agent_id, to_version)
    if diff is None:
        raise HTTPException(status_code=404, detail="no diff recorded for this version")
    return PlainTextResponse(diff)


@router.get("/agents/{agent_id}/compare")
def compare(
    agent_id: str,
    conn: Conn,
    case_id: Annotated[str, Query(description="case id to compare across versions")],
) -> dict[str, Any]:
    """One case's output at v0 vs the current version."""
    if agent_row(conn, agent_id) is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return metrics.compare(conn, agent_id, case_id)
