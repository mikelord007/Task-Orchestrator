"""Minimal reads from the ``agents`` table (``backend/migrations/0001_init.sql``).

The runtime only needs an agent's ``evaluator_id`` and ``current_version``;
everything else about agents belongs to W3.
"""

from __future__ import annotations

from typing import Any


def resolve_agent(agent_id: str) -> dict[str, Any]:
    """Row from ``agents`` as a dict, or ``{}`` if the agent does not exist."""
    from backend.db import init_db

    connection = init_db()
    try:
        row = connection.execute(
            "SELECT agent_id, goal, domain, evaluator_id, current_version, created_ts "
            "FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    finally:
        connection.close()
    return dict(row) if row is not None else {}
