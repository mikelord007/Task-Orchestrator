"""Test doubles for the architect tests. Not backend.testing.fake_llm (Phase 0's, not yet on this branch)."""

from __future__ import annotations


class FakeComplete:
    """A scripted stand-in for ``backend.llm.complete``.

    Matches the same shape: ``complete(messages, model) -> {"text",
    "tool_calls", "usage": {"tokens_in", "tokens_out"}, "cost_usd"}``. Pass a
    list of response texts; each call consumes the next one in order. Every
    call is recorded in ``.calls`` for assertions.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(
        self, messages: list[dict], model: str, tools: list[dict] | None = None
    ) -> dict:
        self.calls.append({"messages": messages, "model": model, "tools": tools})
        if not self._responses:
            raise AssertionError("FakeComplete ran out of scripted responses")
        text = self._responses.pop(0)
        return {
            "text": text,
            "tool_calls": [],
            "usage": {"tokens_in": 100, "tokens_out": 50},
            "cost_usd": 0.001,
        }
