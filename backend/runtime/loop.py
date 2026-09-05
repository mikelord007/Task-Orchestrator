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
            "tokens_out": int(
                usage.get("tokens_out") or usage.get("completion_tokens") or 0
            ),
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


def parse_final_json(text: str | None) -> Any:
    """Tolerant JSON parse of the final answer. ``None`` means unparseable."""
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
        if isinstance(parsed, (dict, list)):
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

        transcript.record_request(
            model=model, messages=messages, tools=specs, phase=phase
        )
        response = normalize_response(
            complete(messages, model=model, tools=specs or None)
        )
        transcript.record_response(
            model=model,
            text=response.text,
            tool_calls=response.tool_calls,
            usage=response.usage,
            cost_usd=response.cost_usd,
            phase=phase,
        )

        assistant: dict[str, Any] = {"role": "assistant", "content": response.text}
        if response.tool_calls:
            assistant["tool_calls"] = response.tool_calls
        messages.append(assistant)

        for raw_call in response.tool_calls:
            call_id, name, args = parse_tool_call(raw_call)
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

        decision = watchdog.check(transcript)
        if decision is not None:
            _handle(decision, transcript, messages, on_drift, result)
            if decision.action == ACTION_ABORT:
                return result
            continue

        if not response.tool_calls:
            parsed = parse_final_json(response.text)
            # Off-task detection only ever inspects "act" phase messages, so
            # the grace period below only applies there; a planning call (or
            # any non-"act" phase) always terminates on its own text.
            if parsed is not None or not watchdog.expected_keys or phase != "act":
                result.final_text = response.text
                result.final_output = parsed
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
