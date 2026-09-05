"""Resolves the LLM completion function the architect's steps call.

Every step function accepts an explicit ``complete`` callable, so tests inject
``backend.testing.fake_llm.FakeLLM`` (via ``backend.llm.set_client`` +
``backend.llm.complete``, or any other object matching ``CompleteFn``) instead
of the real thing. ``resolve_complete`` is only the default used when no
``complete`` is passed in, e.g. from ``api.py``.
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
