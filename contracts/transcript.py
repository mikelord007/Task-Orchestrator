"""Per-task transcript contract (PLAN.md section 2.8 / PLAN_ADDENDUM.md section B).

The transcript is the **harness-level record of what the agent actually did**:
every request, every response, every tool call and its return value, every
nudge, and the token counts reported by the API. It is written by the runtime,
never by the agent, and it is the single source of truth for the drift
watchdog, the failure analyst, the reflection step and Neatlogs.

One file per (task, trial)::

    runs/<run_id>/<case_id>.t<trial>.json

See `contracts/transcript.md` for the prose contract.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.events import DriftAction, DriftKind

__all__ = [
    "StepKind",
    "TranscriptStep",
    "TranscriptDrift",
    "Transcript",
    "transcript_path",
    "load_transcript",
]


class StepKind(StrEnum):
    """What one line of the transcript records."""

    request = "request"
    response = "response"
    tool_call = "tool_call"
    tool_return = "tool_return"
    nudge = "nudge"


class TranscriptStep(BaseModel):
    """One observed step. Which optional fields are set depends on `kind`.

    | kind | fields |
    |---|---|
    | `request` | `model`, `messages` |
    | `response` | `model`, `text`, `tokens_in`, `tokens_out` |
    | `tool_call` | `tool`, `args` |
    | `tool_return` | `tool`, `result` or `error` |
    | `nudge` | `text` (the injected system message) |
    """

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    i: int
    ts: str
    kind: StepKind
    model: str | None = None
    messages: list[dict[str, Any]] | None = None
    text: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: str | None = None
    error: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class TranscriptDrift(BaseModel):
    """A drift trigger on this task, mirroring the `drift_detected` event."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    kind: DriftKind
    step: int
    action: DriftAction


class Transcript(BaseModel):
    """The whole per-(task, trial) record. Totals are sums over observed steps."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    case_id: str
    trial: int
    agent_id: str
    version: int
    started_ts: str
    finished_ts: str
    steps: list[TranscriptStep] = Field(default_factory=list)
    final_output: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    rules_injected: list[str] = Field(default_factory=list)
    drift: list[TranscriptDrift] = Field(default_factory=list)

    def write(self, root: Path | str = "runs") -> Path:
        """Write to `runs/<run_id>/<case_id>.t<trial>.json` and return the path."""
        path = transcript_path(self.run_id, self.case_id, self.trial, root=root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), indent=2), encoding="utf-8")
        return path


def transcript_path(run_id: str, case_id: str, trial: int, root: Path | str = "runs") -> Path:
    """The one path convention for transcripts. Do not build it by hand."""
    return Path(root) / run_id / f"{case_id}.t{trial}.json"


def load_transcript(path: Path | str) -> Transcript:
    """Read and validate a transcript file."""
    return Transcript.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
