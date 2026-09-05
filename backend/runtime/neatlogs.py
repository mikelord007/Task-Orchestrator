"""Optional Neatlogs tracing.

If ``NEATLOGS_API_KEY`` is set and the SDK is importable, each eval case is
wrapped in one trace and its URL lands in ``case_result.trace_url``. Otherwise
this is skipped silently. The local transcript JSON is always written either
way, so nothing downstream depends on Neatlogs being configured.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class Trace:
    url: str | None = None


def enabled() -> bool:
    return bool(os.environ.get("NEATLOGS_API_KEY"))


def _start(name: str, metadata: dict[str, Any]) -> Any:
    import neatlogs  # type: ignore[import-not-found]

    for attr in ("start_trace", "trace", "start_session"):
        factory = getattr(neatlogs, attr, None)
        if callable(factory):
            return factory(name=name, metadata=metadata)
    return None


def _url_of(handle: Any) -> str | None:
    for attr in ("url", "trace_url", "session_url"):
        value = getattr(handle, attr, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(handle, dict):
        for key in ("url", "trace_url", "session_url"):
            value = handle.get(key)
            if isinstance(value, str) and value:
                return value
    return None


@contextmanager
def trace_case(name: str, **metadata: Any) -> Iterator[Trace]:
    """Yield a :class:`Trace`; ``url`` stays ``None`` when tracing is off."""
    trace = Trace()
    if not enabled():
        yield trace
        return
    handle = None
    try:
        handle = _start(name, metadata)
        trace.url = _url_of(handle)
    except Exception:  # noqa: BLE001 - tracing must never fail a run
        handle = None
    try:
        yield trace
    finally:
        if handle is not None:
            try:
                if trace.url is None:
                    trace.url = _url_of(handle)
                finish = getattr(handle, "end", None) or getattr(handle, "finish", None)
                if callable(finish):
                    finish()
            except Exception:  # noqa: BLE001 - see above
                pass
