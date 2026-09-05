"""Current-case context for tools.

Tools (W3's toolbox, W3/W4's GitHub tools) read the case being executed from
``contracts.context.current_case``. The runtime sets it before a case and resets
it afterwards.

``contracts.context.current_case`` may be a ``ContextVar`` or a plain module
attribute; both are supported. Cases run on a thread pool, so a ``ContextVar``
is the safe shape - a plain module attribute is set and restored per case but
would be shared across concurrent cases.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

_ATTR = "current_case"


def _context_module() -> Any | None:
    try:
        from contracts import context  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - contracts unavailable, tools get nothing
        return None
    return context


@contextmanager
def case_scope(case: Any) -> Iterator[None]:
    """Expose ``case`` to tools for the duration of the block."""
    module = _context_module()
    if module is None:
        yield
        return
    holder = getattr(module, _ATTR, None)
    if hasattr(holder, "set") and hasattr(holder, "reset"):
        token = holder.set(case)
        try:
            yield
        finally:
            holder.reset(token)
        return
    previous = holder
    setattr(module, _ATTR, case)
    try:
        yield
    finally:
        setattr(module, _ATTR, previous)


def current_case() -> Any:
    module = _context_module()
    if module is None:
        return None
    holder = getattr(module, _ATTR, None)
    if hasattr(holder, "get"):
        try:
            return holder.get()
        except LookupError:
            return None
    return holder
