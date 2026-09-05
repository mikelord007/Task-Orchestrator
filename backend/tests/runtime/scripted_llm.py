"""Per-task/per-turn dispatch on top of the project's real FakeLLM.

``backend/testing/fake_llm.py`` replays one fixed, ordered list of responses -
exactly right for a single case/trial, but the eval-harness tests here run
many tasks at many trials, each wanting its own tool-call script (a task that
loops, one that raises, one that answers immediately, ...). ``ScriptedLLM``
keeps that per-(case_id, turn) dispatch, but every single call is still routed
through ``backend.llm.set_client(FakeLLM([...])) -> backend.llm.complete()``
and back - the real request/response marshalling runs for every call, not a
hand-rolled shortcut. No network, ever.

``backend.llm``'s injected client is one module-global, so calls are
serialized with a lock: correctness of the eval harness under
``EVAL_CONCURRENCY`` depends on case/tool-call orchestration overlapping, not
on the fake LLM calls themselves truly running in parallel.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Any

from backend import llm as llm_module
from backend.testing.fake_llm import FakeLLM, ScriptedResponse

Handler = Callable[[str, int, list[dict[str, Any]]], dict[str, Any]]

_CASE_ID = re.compile(r"^Case id:\s*(\S+)", re.MULTILINE)


def response(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    tokens_in: int = 100,
    tokens_out: int = 50,
) -> dict[str, Any]:
    """One handler return value, in the shape ``ScriptedLLM`` expects."""
    return {
        "text": text,
        "tool_calls": tool_calls or [],
        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
    }


def tool_call(name: str, args: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    return {"id": call_id or f"call_{name}", "name": name, "args": args}


def _to_scripted_response(raw: dict[str, Any]) -> ScriptedResponse:
    usage = raw.get("usage") or {}
    return ScriptedResponse(
        text=raw.get("text") or "",
        tool_calls=[
            {"id": call.get("id"), "name": call["name"], "arguments": call.get("args") or {}}
            for call in raw.get("tool_calls") or []
        ],
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
    )


class ScriptedLLM:
    """Dispatches to a handler by (case_id, turn), then replays its answer
    through the real ``backend.llm.complete`` + ``FakeLLM``."""

    _lock = threading.Lock()

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        case_id = self.case_id_of(messages)
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        raw = self._handler(case_id, turn, messages)
        with self._lock:
            self.calls.append({"case_id": case_id, "turn": turn, "model": model})
            llm_module.set_client(FakeLLM([_to_scripted_response(raw)]))
            try:
                return llm_module.complete(messages, model=model, tools=tools)
            finally:
                llm_module.reset_client()

    @staticmethod
    def case_id_of(messages: list[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") != "user":
                continue
            match = _CASE_ID.search(str(message.get("content") or ""))
            if match:
                return match.group(1)
        return ""
