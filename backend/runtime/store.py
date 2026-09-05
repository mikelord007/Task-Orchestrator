"""Minimal reads from the ``agents`` table.

The runtime only needs an agent's ``evaluator_id`` and ``current_version``;
everything else about agents belongs to W3.
"""

from __future__ import annotations

from typing import Any


def resolve_agent(agent_id: str) -> dict[str, Any]:
    """Row from ``agents`` as a dict, or ``{}`` if it cannot be read."""
    try:
        from backend import db

        connection = None
        for name in ("connect", "get_connection", "connection"):
            factory = getattr(db, name, None)
            if callable(factory):
                connection = factory()
                break
        if connection is None:
            return {}
        try:
            row = connection.execute(
                "SELECT agent_id, goal, domain, evaluator_id, current_version, created_ts "
                "FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
    except Exception:  # noqa: BLE001 - callers pass explicit values in tests
        return {}
    return dict(row) if row is not None else {}
