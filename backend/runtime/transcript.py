"""Transcript builder - the harness's own record of what an agent did.

PLAN.md rule 2.8: everything here is written by the runtime as it happens. No
step is ever produced by asking the model to describe its own behaviour, and
``passed`` comes from the grader (``score.py``) only.

The transcript is the single source of truth for the drift watchdog, the
failure analyst (W6), W1's ``tool_call_stats`` and Neatlogs. Recording happens
through this convenient mutable builder; :meth:`write` (and :meth:`to_dict`)
produce the exact shape ``contracts.transcript.Transcript`` validates -
``i``/``kind`` per step (not this module's earlier ``index``/``type``),
``result``/``error`` as separate optional strings on a ``tool_return`` step,
``drift`` as its own top-level list rather than steps mixed in, and
``version`` (not ``agent_version``) at the top level. Extra bookkeeping this
module wants (``phase``, ``cost_usd``, per-step ``elapsed_ms``, ...) rides
along as allowed extra fields (the contract's models are ``extra="allow"``).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.transcript import Transcript as ContractTranscript
from contracts.transcript import transcript_path as contract_transcript_path


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def transcript_path(runs_dir: Path | str, run_id: str, case_id: str, trial: int) -> Path:
    """``runs/<run_id>/<case_id>.t<trial>.json`` - the one contract path convention."""
    return contract_transcript_path(run_id, case_id, trial, root=runs_dir)


def _estimate_tokens(text: str | None) -> int:
    """~4 characters per token.

    Used only for a ``tool_return`` step's ``tokens_in``, which the API gives
    us no exact per-tool-call attribution for: the "usage" field on the next
    LLM response covers the whole growing prompt, not just this tool's
    contribution to it. This is a documented approximation, not a measurement
    (W1's ``tool_call_stats`` reads it as such).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


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
    """Append-only in-memory transcript for one (task, trial)."""

    def __init__(
        self,
        *,
        run_id: str,
        agent_id: str,
        agent_version: int,
        case_id: str,
        trial: int,
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
        self.trial = trial
        self.orchestration = orchestration
        self.case_input = case_input
        self.expected_keys = list(expected_keys or [])
        self.system_prompt = system_prompt
        # Written by the runtime, never by the agent (PLAN_ADDENDUM.md section E/0).
        self.rules_injected = list(rules_injected or [])
        self.tool_notes_injected = list(tool_notes_injected or [])

        self.started_ts = utc_now()
        self._t0 = time.monotonic()
        self.finished_ts: str | None = None
        self.latency_ms: int = 0

        self.steps: list[dict[str, Any]] = []
        self.drift: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
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
        # kind is positional-only: some payloads carry their own "kind" field
        # (drift, before it moved to its own list) which would otherwise
        # collide with this one's keyword name.
        step = {
            "i": len(self.steps),
            "kind": kind,
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
            tokens_in=t_in,
            tokens_out=t_out,
            tool_calls=json.loads(json.dumps(tool_calls or [], default=str)),
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
            # The exact dict passed to run() - W1's redundant-call detection
            # (same tool + identical normalized args within one trial) needs
            # the raw shape, not a rendered string.
            args=json.loads(json.dumps(args, default=str)),
            call_id=call_id,
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
            result=None if is_error else result,
            error=result if is_error else None,
            # See _estimate_tokens: an approximation, not a measurement - the
            # API gives no exact per-tool-call token attribution.
            tokens_in=_estimate_tokens(result),
            call_id=call_id,
            duration_ms=duration_ms,
        )

    def record_nudge(self, *, kind: str, message: str) -> None:
        self._append("nudge", text=message, drift_kind=kind)

    def record_drift(self, payload: dict[str, Any], event_id: int | None = None) -> None:
        """Append one drift trigger to ``drift[]`` - a dedicated top-level
        list per the contract, not a step (``StepKind`` has no "drift" value)."""
        entry = dict(payload)
        if event_id is not None:
            entry["event_id"] = event_id
            self.drift_event_id = event_id
        self.drift.append(entry)

    def record_note(self, note: str, **payload: Any) -> None:
        """Runtime commentary (a plan produced by the planning step, a
        swallowed exception, ...) that isn't one of the five contract step
        kinds. Kept as an allowed extra top-level list, not in ``steps``."""
        self.notes.append({"ts": utc_now(), "note": note, **payload})

    # -- finishing ------------------------------------------------------

    def finish(self) -> None:
        if self.finished_ts is None:
            self.finished_ts = utc_now()
            self.latency_ms = int((time.monotonic() - self._t0) * 1000)

    def to_dict(self) -> dict[str, Any]:
        """The exact shape ``contracts.transcript.Transcript`` validates,
        plus this module's own extra fields (allowed by that contract)."""
        self.finish()
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "trial": self.trial,
            "agent_id": self.agent_id,
            "version": self.agent_version,
            "started_ts": self.started_ts,
            "finished_ts": self.finished_ts,
            "steps": self.steps,
            "final_output": self.final_output,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "rules_injected": self.rules_injected,
            "drift": self.drift,
            # -- extras: not part of the contract, allowed alongside it --
            "orchestration": self.orchestration,
            "case_input": self.case_input,
            "expected_keys": self.expected_keys,
            "system_prompt": self.system_prompt,
            "tool_notes_injected": self.tool_notes_injected,
            "notes": self.notes,
            "final_text": self.final_text,
            "aborted": self.aborted,
            "abort_kind": self.abort_kind,
            "trace_url": self.trace_url,
            "cost_usd": round(self.cost_usd, 8),
            "latency_ms": self.latency_ms,
            "llm_calls": self.llm_calls,
            "result": {
                "passed": self.passed,
                "score": self.score,
                "notes": self.score_notes,
                "failure_signature": self.failure_signature,
                "drift_event_id": self.drift_event_id,
            },
        }

    def write(self, runs_dir: Path | str) -> str:
        """Validate against ``contracts.transcript.Transcript`` and write to
        ``runs/<run_id>/<case_id>.t<trial>.json``."""
        validated = ContractTranscript.model_validate(self.to_dict())
        path = validated.write(runs_dir)
        return str(path).replace("\\", "/")
