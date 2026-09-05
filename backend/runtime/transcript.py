"""Transcript builder - the harness's own record of what an agent did.

PLAN.md rule 2.8: everything here is written by the runtime as it happens. No
step is ever produced by asking the model to describe its own behaviour, and
``passed`` comes from the evaluator's ``score.py`` only.

The transcript is the single source of truth for the drift watchdog, the failure
analyst (W6) and Neatlogs. It is persisted to
``runs/<run_id>/<case_id>.r<repeat>.json``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRANSCRIPT_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def transcript_path(runs_dir: Path | str, run_id: str, case_id: str, repeat: int) -> Path:
    """``runs/<run_id>/<case_id>.r<repeat>.json`` (case id made filename-safe)."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(case_id))
    return Path(runs_dir) / run_id / f"{safe}.r{repeat}.json"


@dataclass
class AssistantMessage:
    """A model response as observed by the harness."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    phase: str = "act"

    @property
    def has_tool_call(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class ToolCallRecord:
    tool: str
    normalized_args: str
    step: int


class Transcript:
    """Append-only in-memory transcript for one (case, repeat)."""

    def __init__(
        self,
        *,
        run_id: str,
        agent_id: str,
        agent_version: int,
        case_id: str,
        repeat: int,
        orchestration: str = "single",
        case_input: Any = None,
        expected_keys: list[str] | None = None,
        system_prompt: str = "",
        rules_injected: list[str] | None = None,
        tool_notes_injected: list[str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.agent_id = agent_id
        self.agent_version = agent_version
        self.case_id = case_id
        self.repeat = repeat
        self.orchestration = orchestration
        self.case_input = case_input
        self.expected_keys = list(expected_keys or [])
        self.system_prompt = system_prompt
        # Written by the runtime, never by the agent (PLAN.md 0.2).
        self.rules_injected = list(rules_injected or [])
        self.tool_notes_injected = list(tool_notes_injected or [])

        self.started_ts = utc_now()
        self._t0 = time.monotonic()
        self.finished_ts: str | None = None
        self.latency_ms: int = 0

        self.steps: list[dict[str, Any]] = []
        self.drift: list[dict[str, Any]] = []
        self.assistant_messages: list[AssistantMessage] = []
        self.tool_call_history: list[ToolCallRecord] = []

        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.llm_calls = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self.first_tool_error: str | None = None

        self.final_text: str | None = None
        self.final_output: Any = None
        self.aborted = False
        self.abort_kind: str | None = None
        self.trace_url: str | None = None

        self.passed: bool | None = None
        self.score: float | None = None
        self.score_notes: str = ""
        self.failure_signature: str | None = None
        self.drift_event_id: int | None = None

    # -- accounting -----------------------------------------------------

    @property
    def step_count(self) -> int:
        """Model turns taken so far (the unit DRIFT_MAX_STEPS bounds)."""
        return self.llm_calls

    @property
    def tokens_used(self) -> int:
        return self.tokens_in + self.tokens_out

    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0

    def _append(self, kind: str, /, **payload: Any) -> dict[str, Any]:
        # kind is positional-only: several payloads (e.g. a drift entry) carry
        # their own "kind" field, which would otherwise collide with this one's
        # keyword name.
        step = {
            "index": len(self.steps),
            "type": kind,
            "ts": utc_now(),
            "elapsed_ms": int((time.monotonic() - self._t0) * 1000),
            **payload,
        }
        self.steps.append(step)
        return step

    # -- recording ------------------------------------------------------

    def record_request(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        phase: str = "act",
    ) -> None:
        self._append(
            "request",
            phase=phase,
            model=model,
            messages=json.loads(json.dumps(messages, default=str)),
            tools=[t.get("name") for t in (tools or [])],
        )

    def record_response(
        self,
        *,
        model: str,
        text: str,
        tool_calls: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        cost_usd: float | None = None,
        phase: str = "act",
    ) -> AssistantMessage:
        usage = usage or {}
        t_in = int(usage.get("tokens_in") or 0)
        t_out = int(usage.get("tokens_out") or 0)
        self.tokens_in += t_in
        self.tokens_out += t_out
        self.cost_usd += float(cost_usd or 0.0)
        self.llm_calls += 1
        self._append(
            "response",
            phase=phase,
            model=model,
            text=text or "",
            tool_calls=json.loads(json.dumps(tool_calls or [], default=str)),
            usage={"tokens_in": t_in, "tokens_out": t_out},
            cost_usd=float(cost_usd or 0.0),
        )
        message = AssistantMessage(text=text or "", tool_calls=list(tool_calls or []), phase=phase)
        self.assistant_messages.append(message)
        return message

    def record_tool_call(
        self, *, tool: str, args: Any, normalized_args: str, call_id: str | None = None
    ) -> None:
        self.tool_calls += 1
        self.tool_call_history.append(
            ToolCallRecord(tool=tool, normalized_args=normalized_args, step=self.step_count)
        )
        self._append(
            "tool_call",
            tool=tool,
            call_id=call_id,
            args=json.loads(json.dumps(args, default=str)),
            normalized_args=normalized_args,
        )

    def record_tool_return(
        self,
        *,
        tool: str,
        result: str,
        is_error: bool,
        duration_ms: int,
        call_id: str | None = None,
    ) -> None:
        if is_error:
            self.tool_errors += 1
            if self.first_tool_error is None:
                self.first_tool_error = result
        self._append(
            "tool_return",
            tool=tool,
            call_id=call_id,
            result=result,
            error=is_error,
            duration_ms=duration_ms,
        )

    def record_nudge(self, *, kind: str, message: str) -> None:
        self._append("nudge", kind=kind, message=message)

    def record_drift(self, payload: dict[str, Any], event_id: int | None = None) -> None:
        entry = dict(payload)
        if event_id is not None:
            entry["event_id"] = event_id
            self.drift_event_id = event_id
        self.drift.append(entry)
        self._append("drift", **entry)

    def record_note(self, note: str, **payload: Any) -> None:
        self._append("note", note=note, **payload)

    # -- finishing ------------------------------------------------------

    def finish(self) -> None:
        if self.finished_ts is None:
            self.finished_ts = utc_now()
            self.latency_ms = int((time.monotonic() - self._t0) * 1000)

    def to_dict(self) -> dict[str, Any]:
        self.finish()
        return {
            "transcript_version": TRANSCRIPT_VERSION,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "case_id": self.case_id,
            "repeat": self.repeat,
            "orchestration": self.orchestration,
            "started_ts": self.started_ts,
            "finished_ts": self.finished_ts,
            "latency_ms": self.latency_ms,
            "case_input": self.case_input,
            "expected_keys": self.expected_keys,
            "system_prompt": self.system_prompt,
            "rules_injected": self.rules_injected,
            "tool_notes_injected": self.tool_notes_injected,
            "steps": self.steps,
            "drift": self.drift,
            "totals": {
                "steps": self.step_count,
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tool_errors": self.tool_errors,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "cost_usd": round(self.cost_usd, 8),
            },
            "final_text": self.final_text,
            "final_output": self.final_output,
            "aborted": self.aborted,
            "abort_kind": self.abort_kind,
            "trace_url": self.trace_url,
            "result": {
                "passed": self.passed,
                "score": self.score,
                "notes": self.score_notes,
                "failure_signature": self.failure_signature,
                "drift_event_id": self.drift_event_id,
            },
        }

    def write(self, runs_dir: Path | str) -> str:
        path = transcript_path(runs_dir, self.run_id, self.case_id, self.repeat)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return str(path).replace("\\", "/")
