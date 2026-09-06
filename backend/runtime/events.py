"""Thin, injectable adapters over ``backend/ledger/emit.py``.

The runtime never talks to sqlite directly - every write and every read here
delegates to the real ``emit()``/``read()``, so the same pydantic validation
and query logic apply whether the call comes from a test or from production.
The indirection exists only so tests can inject a bound-to-a-temp-db pair
without monkeypatching.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

EmitFn = Callable[..., Any]
ReadEventsFn = Callable[..., list[dict[str, Any]]]


def default_emit(kind: str, /, **fields: Any) -> int:
    """``kind`` is positional-only: several payloads (e.g. ``drift_detected``)
    carry their own ``kind`` field, which would otherwise collide with this
    one's keyword name."""
    from backend.ledger.emit import emit

    return emit(kind, **fields)


def default_read_events(
    agent_id: str | None = None, kind: str | None = None
) -> list[dict[str, Any]]:
    """Event rows (oldest first) with ``payload`` already decoded."""
    from backend.ledger.emit import read

    return read(agent_id=agent_id, kind=kind)


def event_id_of(emitted: Any) -> int | None:
    """``emit()`` returns the new row id directly; this tolerates a dict/object
    return too, in case a test double shapes it differently."""
    if isinstance(emitted, int):
        return emitted
    if isinstance(emitted, dict):
        value = emitted.get("id")
        return int(value) if isinstance(value, int) else None
    value = getattr(emitted, "id", None)
    return int(value) if isinstance(value, int) else None
