"""Resolves the LLM completion function the architect's steps call.

``backend.llm`` is Phase 0's responsibility and is not yet on ``main`` while
this module is written. ``resolve_complete`` defers that import to call time
so ``backend.architect`` imports cleanly today; every step function also
accepts an explicit ``complete`` callable so tests never need the real thing.
"""

from __future__ import annotations

from typing import Protocol


class CompleteFn(Protocol):
    def __call__(
        self, messages: list[dict], model: str, tools: list[dict] | None = None
    ) -> dict: ...


def resolve_complete() -> CompleteFn:
    from backend.llm import complete  # type: ignore[import-not-found]

    return complete
