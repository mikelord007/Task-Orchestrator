"""Event-ledger payload contracts (PLAN_ADDENDUM.md section A, superseding the
PLAN.md 4.1 / 0.2 shapes wherever they conflict).

The ledger is append-only. Display status is never stored: every metric is a
pure function over these rows.

    events(id, ts, kind, agent_id, agent_version, run_id, lever, payload)

One pydantic model per event `kind` lives here. `ledger.emit()` validates the
payload against `PAYLOAD_MODELS[kind]` before insert.

**Vocabulary (section J):** a *task* is one `case_id`; a *trial* is one
repeated attempt at a task (`0..trials-1`); the *grader* is `score.py`. These
words appear in prose, UI and docstrings. Event field names stay as the
contract defines them below (`case_id`, `trial`) regardless of the prose word.

**pass@1 / pass^k (used everywhere, never call this "accuracy"):**

* `pass@1` = the mean per-trial pass rate over tasks (average of `passes /
  trials` across tasks).
* `pass^k` (k = trials) = the fraction of tasks that passed **every** trial.
  Those tasks are the **stable pass set**. The improvement gate (W6) accepts a
  candidate on `pass^k`, never on `pass@1` alone, so a lucky trial cannot pass
  the gate.
* `pass_rate_std` / `_min` / `_max` are computed over the per-trial run-level
  pass rates (the spread across repeated trials of the whole run), not over
  tasks.

**Flat floats vs. `PassRateStat` -- a boundary worth stating once:** ledger
*events* (`run_finished`, `fix_accepted`, `fix_rejected`) always store flat
float fields (`pass_at_1`, `pass_pow_k`, ...), because an event is one
observed fact and a fact does not need a nested shape. `PassRateStat` (mean,
std, min, max) exists only as the return type of W1's metric *functions* and
the `/insights` chart series, where a caller wants mean-with-spread bundled
together for a version. Do not add `PassRateStat` back into an event payload.

Design decisions taken in Phase 0 where the contract was ambiguous:

* Payload models use ``extra="forbid"``. A stray or misspelled key is a bug,
  not a future-proofing gap -- the trial/repeat rename in this very file is
  the failure mode `extra="allow"` would have hidden. The few kinds that
  legitimately want to carry ad hoc, worker-specific context (`case_result`,
  `fix_proposed`, `drift_detected`) get an explicit ``extra: dict`` field
  instead, so the escape hatch is visible in the schema.
* `case_result` accepts a legacy `repeat` key as an alias for the canonical
  `trial` field: if only `repeat` is given, it is copied to `trial`; if only
  `trial` is given, `repeat` is filled in to match, for any reader still on
  the old name. Passing both with different values is rejected.
* `MemoryWritten.source` and `MemoryRule.source` are the same vocabulary
  (`reflection | issue`) but modelled separately: the memory contract
  (`contracts/agent.py`) needs `Literal` for a JSONL row that is hand-authored
  and diffed, while the ledger uses the shared `MemorySource` enum so every
  event field pulls from one type.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Lever",
    "Split",
    "DriftKind",
    "DriftAction",
    "IssueSource",
    "RejectReason",
    "MemoryEntryKind",
    "MemorySource",
    "PassRateStat",
    "FailingGroup",
    "EventPayload",
    "AgentCreated",
    "RunStarted",
    "CaseResult",
    "DriftDetected",
    "RunFinished",
    "IssueOpened",
    "IssueLinkedCase",
    "FixProposed",
    "FixAccepted",
    "FixRejected",
    "LessonRecorded",
    "MemoryWritten",
    "MemoryDemoted",
    "TaskGraduated",
    "PAYLOAD_MODELS",
    "EVENT_KINDS",
    "validate_payload",
]


class Lever(StrEnum):
    """The improvement levers. `routing` is the shrunk per-step model lever.

    `grader` is a fix to `score.py` itself (filed via the "grader disagreed?"
    path, section J) -- it is excluded from the agent's improvement curve.
    """

    prompt = "prompt"
    tools = "tools"
    memory = "memory"
    orchestration = "orchestration"
    routing = "routing"
    grader = "grader"


class Split(StrEnum):
    train = "train"
    holdout = "holdout"


class DriftKind(StrEnum):
    loop = "loop"
    budget = "budget"
    off_task = "off_task"
    step_limit = "step_limit"


class DriftAction(StrEnum):
    abort = "abort"
    nudge = "nudge"


class IssueSource(StrEnum):
    human = "human"
    auto = "auto"


class RejectReason(StrEnum):
    regression = "regression"
    no_gain = "no_gain"
    error = "error"


class MemoryEntryKind(StrEnum):
    rule = "rule"
    tool_note = "tool_note"
    episode = "episode"


class MemorySource(StrEnum):
    reflection = "reflection"
    issue = "issue"


class EventPayload(BaseModel):
    """Base for every payload model. See the module docstring for why
    `extra="forbid"` is the default and which kinds opt out via an explicit
    `extra: dict` field."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class PassRateStat(EventPayload):
    """Mean-with-spread for a version. W1 metric functions and `/insights`
    series only -- never nest this inside an event payload (see module
    docstring)."""

    mean: float
    std: float
    min: float | None = None
    max: float | None = None


class FailingGroup(EventPayload):
    """A deduped group of failures the improver targeted."""

    signature: str
    tag: str | None = None
    case_ids: list[str] = Field(default_factory=list)
    count: int


class AgentCreated(EventPayload):
    goal: str
    domain: str
    tools: list[str]
    evaluator_id: str
    orchestration: str
    applied_lessons: list[str] = Field(default_factory=list)


class RunStarted(EventPayload):
    split: Split
    case_count: int
    trials: int


class CaseResult(EventPayload):
    """One (task, trial) outcome. `passed`/`score` come from the grader only.

    `trial` is canonical (0-based, `0..trials-1`). `repeat` is accepted as a
    legacy alias: supply either one, or both if they agree.
    """

    case_id: str
    trial: int
    repeat: int | None = None
    passed: bool
    score: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    steps: int
    transcript_path: str
    tool_calls: int
    tool_errors: int
    rules_injected: list[str] = Field(default_factory=list)
    trace_url: str | None = None
    failure_signature: str | None = None
    drift_event_id: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_repeat_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        has_trial, has_repeat = "trial" in data, "repeat" in data
        if has_trial and has_repeat and data["trial"] != data["repeat"]:
            raise ValueError(
                f"trial ({data['trial']!r}) and repeat ({data['repeat']!r}) disagree; "
                "pass only one, or make them equal"
            )
        if has_repeat and not has_trial:
            data = {**data, "trial": data["repeat"]}
        return data

    @model_validator(mode="after")
    def _sync_repeat(self) -> CaseResult:
        if self.repeat is None:
            self.repeat = self.trial
        return self


class DriftDetected(EventPayload):
    case_id: str
    trial: int
    step: int
    kind: DriftKind
    evidence: str
    action: DriftAction
    tokens_at_detection: int
    extra: dict[str, Any] = Field(default_factory=dict)


class RunFinished(EventPayload):
    """One run's summary. See the module docstring for the pass@1 / pass^k
    definitions and why these fields are flat floats, not `PassRateStat`."""

    split: Split
    trials: int
    pass_at_1: float
    pass_pow_k: float
    pass_rate_std: float
    pass_rate_min: float
    pass_rate_max: float
    total_cost_usd: float
    p50_latency_ms: int
    p95_latency_ms: int
    drift_count: int
    tokens_saved_by_drift: int


class IssueOpened(EventPayload):
    issue_id: str
    source: IssueSource
    title: str
    failure_signature: str | None = None


class IssueLinkedCase(EventPayload):
    issue_id: str
    case_id: str


class FixProposed(EventPayload):
    from_version: int
    to_version: int
    lever: Lever
    failing_group: FailingGroup
    hypothesis: str
    diagnosis: str
    diff_path: str
    diff_summary: str
    files_touched: list[str] = Field(default_factory=list)
    issue_id: str | None = None
    metric_signal: str | None = None
    """For lever=tools: the tracked-metric heuristic that drove the diagnosis,
    e.g. "12 redundant list_issues calls/task" or "6 invalid-parameter errors
    on get_issue" (section K)."""
    extra: dict[str, Any] = Field(default_factory=dict)


class FixAccepted(EventPayload):
    to_version: int
    pass_at_1_before: float
    pass_at_1_after: float
    pass_pow_k_before: float
    pass_pow_k_after: float
    group_pass_before: float
    group_pass_after: float
    holdout_pass_at_1_after: float
    holdout_pass_pow_k_after: float
    cost_per_run_before: float
    cost_per_run_after: float
    tool_calls_per_task_before: float
    tool_calls_per_task_after: float


class FixRejected(EventPayload):
    to_version: int
    reason: RejectReason
    regressed_case_ids: list[str] = Field(default_factory=list)
    candidate_pass_at_1: float


class LessonRecorded(EventPayload):
    lesson_id: str
    lever: Lever
    trigger: str
    lesson: str
    source_agent_id: str
    source_issue_id: str | None = None


class MemoryWritten(EventPayload):
    """A memory entry the agent proposed and the gate accepted (section E)."""

    entry_id: str
    kind: MemoryEntryKind
    source: MemorySource
    evidence_case_ids: list[str] = Field(default_factory=list)
    version: int


class MemoryDemoted(EventPayload):
    """A rule with misses > hits after >= 4 uses; kept on disk, not injected."""

    entry_id: str
    hits: int
    misses: int
    version: int


class TaskGraduated(EventPayload):
    """A task that entered this version's stable pass set (pass^k) having not
    been in the prior version's (section J). For v0, every stably-passing task
    graduates. W1 exposes the running total as `graduated_count`."""

    case_id: str
    version: int


PAYLOAD_MODELS: dict[str, type[EventPayload]] = {
    "agent_created": AgentCreated,
    "run_started": RunStarted,
    "case_result": CaseResult,
    "drift_detected": DriftDetected,
    "run_finished": RunFinished,
    "issue_opened": IssueOpened,
    "issue_linked_case": IssueLinkedCase,
    "fix_proposed": FixProposed,
    "fix_accepted": FixAccepted,
    "fix_rejected": FixRejected,
    "lesson_recorded": LessonRecorded,
    "memory_written": MemoryWritten,
    "memory_demoted": MemoryDemoted,
    "task_graduated": TaskGraduated,
}

EVENT_KINDS: tuple[str, ...] = tuple(PAYLOAD_MODELS)


def validate_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate `payload` for event `kind`, returning the normalized JSON dict.

    Raises `KeyError` for an unknown kind and `pydantic.ValidationError` for a
    payload that does not satisfy the contract.
    """
    try:
        model = PAYLOAD_MODELS[kind]
    except KeyError:
        raise KeyError(
            f"unknown event kind {kind!r}; expected one of {', '.join(EVENT_KINDS)}"
        ) from None
    return model.model_validate(payload).model_dump(mode="json")
