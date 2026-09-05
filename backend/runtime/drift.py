"""Drift watchdog.

Evaluated after every step of the loop, from *observed* transcript state only
(PLAN.md rule 2.8) - the watchdog never asks the agent whether it is stuck.

Four kinds:

``loop``
    The same tool called with the same normalized args ``DRIFT_REPEAT_CALL_LIMIT``
    times -> nudge once; a second trigger on the same case -> abort.
``budget``
    Cumulative tokens for the case exceed ``DRIFT_TOKEN_BUDGET`` -> abort. The
    per-case wall-clock timeout is also accounted here.
``step_limit``
    Steps exceed ``DRIFT_MAX_STEPS`` -> abort.
``off_task``
    The last two assistant messages contain none of the expected output keys and
    made no tool call -> nudge with the expected schema; abort on repeat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.runtime.config import Knobs

if TYPE_CHECKING:  # pragma: no cover
    from backend.runtime.transcript import Transcript

DRIFT_KINDS = ("loop", "budget", "step_limit", "off_task")
ACTION_NUDGE = "nudge"
ACTION_ABORT = "abort"

# Exact wording from PLAN.md section 6, W2.
LOOP_NUDGE_TEMPLATE = (
    "You have called `{tool}` with identical arguments {count} times. "
    "Change approach or answer with what you have."
)
OFF_TASK_NUDGE_TEMPLATE = (
    "Your last two messages made no tool call and contained none of the expected "
    "output keys. Stop exploring and answer now with a single JSON object using "
    "exactly this schema: {schema}"
)

_MESSAGE_EXCERPT_CHARS = 240


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, str):
        return value.strip().lower()
    return value


def normalize_args(args: Any) -> str:
    """Stable string form of tool arguments, used to detect identical calls."""
    return json.dumps(
        _canonicalize(args), sort_keys=True, separators=(",", ":"), default=str
    )


@dataclass(frozen=True)
class DriftDecision:
    kind: str
    action: str
    evidence: dict[str, Any]
    tokens_at_detection: int
    step: int
    message: str | None = None

    def to_payload(self, *, case_id: str, trial: int) -> dict[str, Any]:
        """The ``drift_detected`` payload (PLAN_ADDENDUM.md section A)."""
        return {
            "case_id": case_id,
            "trial": trial,
            "step": self.step,
            "kind": self.kind,
            "evidence": self.evidence,
            "action": self.action,
            "tokens_at_detection": self.tokens_at_detection,
        }


class DriftWatchdog:
    """Per-case watchdog. Call :meth:`check` after every step."""

    def __init__(self, knobs: Knobs, expected_keys: list[str] | None = None) -> None:
        self.knobs = knobs
        self.expected_keys = [str(k) for k in (expected_keys or [])]
        self._loop_reported: dict[tuple[str, str], int] = {}
        self._loop_triggers = 0
        self._off_task_triggers = 0
        self._off_task_reported_at = -1
        self._terminal = False

    # -- checks ---------------------------------------------------------

    def check(self, transcript: Transcript) -> DriftDecision | None:
        """First drift decision produced by the current transcript state, if any."""
        if self._terminal:
            return None
        # Order per PLAN_ADDENDUM.md section C: loop and budget are the most
        # concrete signals, step_limit next, off_task last (least reliable,
        # first on the cut list).
        for probe in (
            self._check_loop,
            self._check_budget,
            self._check_step_limit,
            self._check_off_task,
        ):
            decision = probe(transcript)
            if decision is not None:
                if decision.action == ACTION_ABORT:
                    self._terminal = True
                return decision
        return None

    def check_timeout(self, transcript: Transcript) -> DriftDecision | None:
        """Per-case wall-clock timeout, recorded as a ``budget`` abort for accounting."""
        if self._terminal:
            return None
        elapsed = transcript.elapsed_s()
        if elapsed < self.knobs.case_timeout_s:
            return None
        self._terminal = True
        return DriftDecision(
            kind="budget",
            action=ACTION_ABORT,
            evidence={
                "reason": "case_timeout",
                "elapsed_s": round(elapsed, 3),
                "timeout_s": self.knobs.case_timeout_s,
                "tokens_used": transcript.tokens_used,
            },
            tokens_at_detection=transcript.tokens_used,
            step=transcript.step_count,
        )

    # -- individual kinds -----------------------------------------------

    def _check_budget(self, transcript: Transcript) -> DriftDecision | None:
        used = transcript.tokens_used
        if used <= self.knobs.drift_token_budget:
            return None
        return DriftDecision(
            kind="budget",
            action=ACTION_ABORT,
            evidence={"tokens_used": used, "budget": self.knobs.drift_token_budget},
            tokens_at_detection=used,
            step=transcript.step_count,
        )

    def _check_step_limit(self, transcript: Transcript) -> DriftDecision | None:
        steps = transcript.step_count
        if steps <= self.knobs.drift_max_steps:
            return None
        return DriftDecision(
            kind="step_limit",
            action=ACTION_ABORT,
            evidence={"steps": steps, "max_steps": self.knobs.drift_max_steps},
            tokens_at_detection=transcript.tokens_used,
            step=steps,
        )

    def _check_loop(self, transcript: Transcript) -> DriftDecision | None:
        limit = self.knobs.drift_repeat_call_limit
        if limit <= 0 or not transcript.tool_call_history:
            return None
        counts: dict[tuple[str, str], int] = {}
        for record in transcript.tool_call_history:
            key = (record.tool, record.normalized_args)
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            if count < limit or count <= self._loop_reported.get(key, 0):
                continue
            self._loop_reported[key] = count
            self._loop_triggers += 1
            action = ACTION_NUDGE if self._loop_triggers == 1 else ACTION_ABORT
            tool, args = key
            return DriftDecision(
                kind="loop",
                action=action,
                evidence={"tool": tool, "args": args, "count": count, "limit": limit},
                tokens_at_detection=transcript.tokens_used,
                step=transcript.step_count,
                message=LOOP_NUDGE_TEMPLATE.format(tool=tool, count=count),
            )
        return None

    def _check_off_task(self, transcript: Transcript) -> DriftDecision | None:
        if not self.expected_keys:
            return None
        # Only the acting phase can be "off task"; a planner's prose is prose by
        # construction and must not be mistaken for a wandering answer.
        messages = [m for m in transcript.assistant_messages if m.phase == "act"]
        if len(messages) < 2:
            return None
        last_index = len(messages) - 1
        if last_index <= self._off_task_reported_at:
            return None
        recent = messages[-2:]
        for message in recent:
            if message.has_tool_call:
                return None
            lowered = (message.text or "").lower()
            if any(key.lower() in lowered for key in self.expected_keys):
                return None
        self._off_task_reported_at = last_index
        self._off_task_triggers += 1
        action = ACTION_NUDGE if self._off_task_triggers == 1 else ACTION_ABORT
        schema = "{" + ", ".join(f'"{k}": ...' for k in self.expected_keys) + "}"
        return DriftDecision(
            kind="off_task",
            action=action,
            evidence={
                "expected_keys": list(self.expected_keys),
                "last_messages": [
                    (m.text or "")[:_MESSAGE_EXCERPT_CHARS] for m in recent
                ],
            },
            tokens_at_detection=transcript.tokens_used,
            step=transcript.step_count,
            message=OFF_TASK_NUDGE_TEMPLATE.format(schema=schema),
        )
