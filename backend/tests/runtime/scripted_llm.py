"""Local stand-in for ``backend/testing/fake_llm.py``.

Phase 0 had not merged when this workstream started, so the runtime tests script
model responses through this shim. It is replaced by the shared FakeLLM once
that lands; nothing outside ``backend/tests/runtime/`` imports it.

The handler is called with ``(case_id, turn, messages)`` where ``turn`` is the
number of assistant messages already in the conversation, so it is stateless and
safe under the eval harness's thread pool.
"""

from __future__ import annotations

import re
from typing import Any, Callable

Handler = Callable[[str, int, list[dict[str, Any]]], dict[str, Any]]

_CASE_ID = re.compile(r"^Case id:\s*(\S+)", re.MULTILINE)


def response(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    tokens_in: int = 100,
    tokens_out: int = 50,
    cost_usd: float = 0.0002,
) -> dict[str, Any]:
    """One ``llm.complete`` return value."""
    return {
        "text": text,
        "tool_calls": tool_calls or [],
        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
        "cost_usd": cost_usd,
    }


def tool_call(name: str, args: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    return {"id": call_id or f"call_{name}", "name": name, "args": args}


class ScriptedLLM:
    """Replays scripted responses. No network, ever."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        case_id = self.case_id_of(messages)
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        self.calls.append({"case_id": case_id, "turn": turn, "model": model})
        return self._handler(case_id, turn, messages)

    @staticmethod
    def case_id_of(messages: list[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") != "user":
                continue
            match = _CASE_ID.search(str(message.get("content") or ""))
            if match:
                return match.group(1)
        return ""
