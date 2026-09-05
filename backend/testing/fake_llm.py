"""FakeLLM -- the test double every workstream uses instead of the network.

It mimics the slice of the OpenAI client that `backend.llm.complete` touches
(`client.chat.completions.create(...)`), replays scripted responses **in order**,
records every request it received, and reports deterministic-but-realistic token
usage so cost and drift-budget maths are exercised.

    from backend import llm
    from backend.testing.fake_llm import FakeLLM, tool_call, text

    fake = FakeLLM([
        tool_call("get_issue", {"number": 412}),
        text('{"labels": ["bug"], "component": "pty"}'),
    ])
    llm.set_client(fake)
    ...
    llm.reset_client()
    assert fake.call_count == 2
    assert fake.requests[0]["model"] == "gpt-4o"

Pass `repeat_last=True` to keep replaying the final response forever -- that is
how the drift watchdog tests build an agent that loops on one tool call.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ScriptedResponse", "FakeLLM", "text", "tool_call", "FakeLLMExhausted"]


class FakeLLMExhausted(AssertionError):
    """The agent asked for more responses than the test scripted."""


@dataclass
class ScriptedResponse:
    """One scripted assistant turn: free text, tool calls, or both."""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    finish_reason: str | None = None


def text(content: str, **kwargs: Any) -> ScriptedResponse:
    """A plain text turn."""
    return ScriptedResponse(text=content, **kwargs)


def tool_call(
    name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
) -> ScriptedResponse:
    """A turn that calls exactly one tool."""
    return ScriptedResponse(tool_calls=[{"name": name, "arguments": arguments or {}}], **kwargs)


# --------------------------------------------------------------------------
# Minimal stand-ins for the OpenAI response objects
# --------------------------------------------------------------------------


@dataclass
class _FakeFunction:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunction
    type: str = "function"


@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: list[_FakeToolCall] | None
    role: str = "assistant"


@dataclass
class _FakeChoice:
    message: _FakeMessage
    finish_reason: str
    index: int = 0


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage
    model: str
    id: str = "fake-completion"


def _estimate_tokens(payload: Any) -> int:
    """~4 characters per token. Deterministic, and close enough for budget maths."""
    if payload is None:
        return 0
    if not isinstance(payload, str):
        payload = json.dumps(payload, sort_keys=True, default=str)
    return max(1, len(payload) // 4)


class _Completions:
    def __init__(self, parent: FakeLLM) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeResponse:
        return self._parent._create(**kwargs)


class _Chat:
    def __init__(self, parent: FakeLLM) -> None:
        self.completions = _Completions(parent)


class FakeLLM:
    """Replays `responses` in order. Records every request in `self.requests`."""

    def __init__(
        self,
        responses: list[ScriptedResponse] | None = None,
        *,
        repeat_last: bool = False,
    ) -> None:
        self.responses: list[ScriptedResponse] = list(responses or [])
        self.repeat_last = repeat_last
        self.requests: list[dict[str, Any]] = []
        self.call_count = 0
        self.chat = _Chat(self)

    # -- scripting ---------------------------------------------------------

    def push(self, *responses: ScriptedResponse) -> FakeLLM:
        """Append more scripted responses (chainable)."""
        self.responses.extend(responses)
        return self

    # -- introspection -----------------------------------------------------

    @property
    def last_request(self) -> dict[str, Any]:
        if not self.requests:
            raise AssertionError("FakeLLM received no requests")
        return self.requests[-1]

    def messages_at(self, index: int) -> list[dict[str, Any]]:
        """The `messages` list of request `index`."""
        return self.requests[index]["messages"]

    def system_prompts(self) -> list[str]:
        """Every system message content the harness sent, in order."""
        return [
            m.get("content") or ""
            for req in self.requests
            for m in req["messages"]
            if m.get("role") == "system"
        ]

    def tool_names_offered(self, index: int = -1) -> list[str]:
        """Tool names passed to the model on request `index`."""
        tools = self.requests[index].get("tools") or []
        return [t["function"]["name"] for t in tools]

    # -- the client surface ------------------------------------------------

    def _next_response(self) -> ScriptedResponse:
        if self.call_count < len(self.responses):
            return self.responses[self.call_count]
        if self.repeat_last and self.responses:
            return self.responses[-1]
        raise FakeLLMExhausted(
            f"FakeLLM ran out of scripted responses after {self.call_count} call(s). "
            "Script another response, or construct with repeat_last=True."
        )

    def _create(self, **kwargs: Any) -> _FakeResponse:
        # Record a deep copy, and record it before consulting the script: a
        # caller that mutates its own `messages` list after the call (a normal
        # thing to do in a tool-use loop) must not rewrite history, and an
        # exhausting call must still show up in `self.requests` so a test can
        # see what request triggered `FakeLLMExhausted`.
        self.requests.append(copy.deepcopy(kwargs))
        scripted = self._next_response()
        self.call_count += 1

        calls = [
            _FakeToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                function=_FakeFunction(
                    name=call["name"],
                    arguments=json.dumps(call.get("arguments") or {}, sort_keys=True),
                ),
            )
            for call in scripted.tool_calls
        ]

        tokens_in = scripted.tokens_in
        if tokens_in is None:
            tokens_in = _estimate_tokens(kwargs.get("messages")) + _estimate_tokens(
                kwargs.get("tools")
            )
        tokens_out = scripted.tokens_out
        if tokens_out is None:
            tokens_out = _estimate_tokens(scripted.text) + sum(
                _estimate_tokens(c.function.arguments) + 4 for c in calls
            )

        finish_reason = scripted.finish_reason or ("tool_calls" if calls else "stop")
        return _FakeResponse(
            choices=[
                _FakeChoice(
                    message=_FakeMessage(
                        content=scripted.text or None,
                        tool_calls=calls or None,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=_FakeUsage(
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                total_tokens=tokens_in + tokens_out,
            ),
            model=kwargs.get("model", "fake-model"),
        )
