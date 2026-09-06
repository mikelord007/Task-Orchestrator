"""The tool-use loop.

One loop, shared by every orchestration mode. It is the only place that talks to
``backend/llm.py``, and it records every request, response, tool call, tool
return, token count and timestamp into the transcript *as it happens*
(PLAN.md rule 2.8). The drift watchdog is consulted after every step, from that
transcript state alone.

A response with no tool call ends the case with its text as the final answer
attempt - unless the text is unparseable *and* off-task detection is active
(expected output keys are known). In that case the loop gives the model one
more turn so the watchdog can see two consecutive off-task messages, rather
than scoring a single stray reply as ``bad_output`` before drift ever gets a
chance to catch a model that never converges.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.runtime.config import Knobs
from backend.runtime.drift import (
    ACTION_ABORT,
    DriftDecision,
    DriftWatchdog,
    normalize_args,
)
from backend.runtime.package import LoadedPackage, invoke_tool
from backend.runtime.transcript import Transcript

CompleteFn = Callable[..., dict[str, Any]]
DriftSink = Callable[[DriftDecision], Any]

_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")


def default_complete(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]] | None = None,
):
    """Every LLM call goes through ``backend/llm.py``."""
    from backend import llm

    return llm.complete(messages, model=model, tools=tools)


# -- response normalization --------------------------------------------


@dataclass
class ModelResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    raw: Any = None


def normalize_response(raw: Any) -> ModelResponse:
    if not isinstance(raw, dict):
        raw = {"text": str(raw or "")}
    usage = raw.get("usage") or {}
    return ModelResponse(
        text=str(raw.get("text") or ""),
        tool_calls=list(raw.get("tool_calls") or []),
        usage={
            "tokens_in": int(usage.get("tokens_in") or usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("tokens_out") or usage.get("completion_tokens") or 0),
        },
        cost_usd=float(raw.get("cost_usd") or 0.0),
        raw=raw,
    )


def parse_tool_call(raw: Any) -> tuple[str | None, str, dict[str, Any]]:
    """Pull ``(call_id, name, args)`` out of a tool call in either common shape."""
    if not isinstance(raw, dict):
        return None, str(raw), {}
    call_id = raw.get("id") or raw.get("call_id") or raw.get("tool_call_id")
    body = raw.get("function") if isinstance(raw.get("function"), dict) else raw
    name = str(body.get("name") or raw.get("tool") or "")
    args = body.get("args")
    if args is None:
        args = body.get("arguments")
    if args is None:
        args = body.get("input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"input": args}
    if not isinstance(args, dict):
        args = {} if args is None else {"input": args}
    return (str(call_id) if call_id is not None else None), name, args


def to_openai_tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """OpenAI wire format for one tool call: ``{id, type, function: {name,
    arguments}}`` with ``arguments`` a JSON *string*.

    ``backend.llm.complete()`` returns tool calls in a simplified shape
    (``arguments`` already a parsed dict) for the harness's convenience, but
    that is not a valid assistant message to echo back on the next turn - a
    real OpenAI-compatible endpoint 400s on it. This is what actually goes
    into ``messages``.
    """
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, default=str)},
    }


def parse_final_json(text: str | None) -> dict[str, Any] | None:
    """Tolerant JSON parse of the final answer. ``None`` means unparseable.

    Only a JSON *object* counts as a real answer: the grader and
    ``contracts.transcript.Transcript.final_output`` both expect a dict, and a
    bare top-level array has no evaluator that scores it. A model that answers
    with an array is treated exactly like one that answers with malformed
    JSON - a ``bad_output`` failure, not a runtime crash.
    """
    if not text:
        return None
    candidate = _FENCE.sub("", text.strip()).strip()
    for attempt in (candidate, _first_json_object(candidate)):
        if not attempt:
            continue
        try:
            parsed = json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _first_json_object(text: str) -> str | None:
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    return None


# -- the loop -----------------------------------------------------------


@dataclass
class LoopResult:
    final_text: str | None = None
    final_output: Any = None
    aborted: bool = False
    drift_kind: str | None = None
    nudged: bool = False


def run_loop(
    *,
    package: LoadedPackage,
    transcript: Transcript,
    messages: list[dict[str, Any]],
    knobs: Knobs,
    watchdog: DriftWatchdog,
    complete: CompleteFn,
    model: str,
    on_drift: DriftSink | None = None,
    use_tools: bool = True,
    phase: str = "act",
) -> LoopResult:
    """Run one tool-use loop to a final answer, an abort, or the hard step ceiling."""
    specs = package.tool_specs() if use_tools else []
    result = LoopResult()
    # Belt and braces: the watchdog owns step_limit, this only bounds the while.
    hard_ceiling = max(knobs.drift_max_steps, 1) + 2

    while transcript.step_count < hard_ceiling:
        timeout = watchdog.check_timeout(transcript)
        if timeout is not None:
            _handle(timeout, transcript, messages, on_drift, result)
            return result

        transcript.record_request(model=model, messages=messages, tools=specs, phase=phase)
        response = normalize_response(complete(messages, model=model, tools=specs or None))
        transcript.record_response(
            model=model,
            text=response.text,
            tool_calls=response.tool_calls,
            usage=response.usage,
            cost_usd=response.cost_usd,
            phase=phase,
        )

        parsed_calls: list[tuple[str, str, dict[str, Any]]] = []
        for raw_call in response.tool_calls:
            call_id, name, args = parse_tool_call(raw_call)
            # A real API always assigns a call id; a fallback exists only for
            # test-scripted calls that omit one, and it must be reused below
            # so the assistant's tool_calls and the tool-role reply agree.
            call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"
            parsed_calls.append((call_id, name, args))

        assistant: dict[str, Any] = {"role": "assistant", "content": response.text}
        if parsed_calls:
            assistant["tool_calls"] = [
                to_openai_tool_call(call_id, name, args) for call_id, name, args in parsed_calls
            ]
        messages.append(assistant)

        for call_id, name, args in parsed_calls:
            transcript.record_tool_call(
                tool=name,
                args=args,
                normalized_args=normalize_args(args),
                call_id=call_id,
            )
            started = time.monotonic()
            tool = package.tools.get(name)
            if tool is None:
                text, is_error = (
                    f"ERROR: unknown tool '{name}'. Available tools: "
                    f"{', '.join(sorted(package.tools)) or 'none'}",
                    True,
                )
            else:
                text, is_error = invoke_tool(tool, args)
            transcript.record_tool_return(
                tool=name,
                result=text,
                is_error=is_error,
                duration_ms=int((time.monotonic() - started) * 1000),
                call_id=call_id,
            )
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "name": name, "content": text}
            )
            # Checked after every tool return, not only once per turn: a
            # turn with several slow tool calls must not run past the
            # timeout just because the cooperative check only ran at the top
            # of the loop (D8).
            timeout = watchdog.check_timeout(transcript)
            if timeout is not None:
                _handle(timeout, transcript, messages, on_drift, result)
                return result

        if not response.tool_calls:
            parsed = parse_final_json(response.text)
            if parsed is not None:
                # A valid answer wins even if this very turn also crossed the
                # token/step budget: the case succeeded, so there is nothing
                # for drift to flag (D7) - checked before watchdog.check()
                # deliberately, so a budget/step_limit trigger never discards
                # a real answer the model already produced.
                result.final_text = response.text
                result.final_output = parsed
                return result

        decision = watchdog.check(transcript)
        if decision is not None:
            _handle(decision, transcript, messages, on_drift, result)
            if decision.action == ACTION_ABORT:
                return result
            continue

        if not response.tool_calls:
            # Off-task detection only ever inspects "act" phase messages, so
            # the grace period below only applies there; a planning call (or
            # any non-"act" phase) always terminates on its own text.
            if not watchdog.expected_keys or phase != "act":
                result.final_text = response.text
                result.final_output = None
                return result
            # Unparseable, no tool call, but off-task detection is active and
            # has not (yet) decided - give the model another turn so the
            # watchdog can see two consecutive off-task messages before this
            # is scored as a bad_output failure instead of drift.
            continue

    # Ran out of turns without the watchdog firing (only reachable if the
    # step_limit knob is disabled); report it as a step_limit abort.
    fallback = DriftDecision(
        kind="step_limit",
        action=ACTION_ABORT,
        evidence={"steps": transcript.step_count, "max_steps": knobs.drift_max_steps},
        tokens_at_detection=transcript.tokens_used,
        step=transcript.step_count,
    )
    _handle(fallback, transcript, messages, on_drift, result)
    return result


def _handle(
    decision: DriftDecision,
    transcript: Transcript,
    messages: list[dict[str, Any]],
    on_drift: DriftSink | None,
    result: LoopResult,
) -> None:
    event_id = on_drift(decision) if on_drift is not None else None
    transcript.record_drift(
        decision.to_payload(case_id=transcript.case_id, trial=transcript.trial),
        event_id=event_id if isinstance(event_id, int) else None,
    )
    if decision.action == ACTION_ABORT:
        result.aborted = True
        result.drift_kind = decision.kind
        transcript.aborted = True
        transcript.abort_kind = decision.kind
        return
    result.nudged = True
    if decision.message:
        transcript.record_nudge(kind=decision.kind, message=decision.message)
        messages.append({"role": "system", "content": decision.message})
