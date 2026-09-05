"""Event-ledger payload contracts (PLAN.md §4.1, amended by §0.2).

The ledger is append-only. Display status is never stored: every metric is a
pure function over these rows.

    events(id, ts, kind, agent_id, agent_version, run_id, lever, payload)

One pydantic model per event `kind` lives here. `ledger.emit()` validates the
payload against `PAYLOAD_MODELS[kind]` before insert.

Design decisions taken in Phase 0 where §4.1 was ambiguous:

* Payload models use ``extra="allow"``. The listed keys are *required*; workers
  may attach extra context without filing a contract change. Typos in required
  keys are still caught, which is what `emit()` is for.
* "mean +/- std" fields (`train_pass_rate_before`, ...) are modelled as the
  nested `PassRateStat` object ``{mean, std, min?, max?}`` rather than two flat
  columns, so the same shape is reused everywhere a pass rate is reported.
* `case_result.repeat` is 0-based (``0..repeats-1``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    "PAYLOAD_MODELS",
    "EVENT_KINDS",
    "validate_payload",
]


class Lever(StrEnum):
    """The improvement levers. `routing` is the §0.4-shrunk per-step model lever."""

    prompt = "prompt"
    tools = "tools"
    memory = "memory"
    orchestration = "orchestration"
    routing = "routing"


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
    """Base for every payload model."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class PassRateStat(EventPayload):
    """A pass rate reported with its spread across repeats (PLAN.md §4.1)."""

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
    repeats: int


class CaseResult(EventPayload):
    """One (case, repeat) outcome. `passed`/`score` come from score.py only."""

    case_id: str
    repeat: int
    passed: bool
    score: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    steps: int
    transcript_path: str
    # §0.2 additions
    tool_calls: int
    tool_errors: int
    rules_injected: list[str] = Field(default_factory=list)
    trace_url: str | None = None
    failure_signature: str | None = None
    drift_event_id: int | None = None


class DriftDetected(EventPayload):
    case_id: str
    repeat: int
    step: int
    kind: DriftKind
    evidence: str
    action: DriftAction
    tokens_at_detection: int


class RunFinished(EventPayload):
    split: Split
    repeats: int
    pass_rate_mean: float
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


class FixAccepted(EventPayload):
    to_version: int
    train_pass_rate_before: PassRateStat
    train_pass_rate_after: PassRateStat
    group_pass_before: float
    group_pass_after: float
    holdout_pass_rate_after: PassRateStat
    cost_per_run_before: float
    cost_per_run_after: float


class FixRejected(EventPayload):
    to_version: int
    reason: RejectReason
    regressed_case_ids: list[str] = Field(default_factory=list)
    train_pass_rate_candidate: PassRateStat


class LessonRecorded(EventPayload):
    lesson_id: str
    lever: Lever
    trigger: str
    lesson: str
    source_agent_id: str
    source_issue_id: str | None = None


class MemoryWritten(EventPayload):
    """§0.2 — a memory entry the agent proposed and the gate accepted."""

    entry_id: str
    kind: MemoryEntryKind
    source: str
    evidence_case_ids: list[str] = Field(default_factory=list)
    version: int


class MemoryDemoted(EventPayload):
    """§0.2 — a rule with misses > hits after >= 4 uses; kept on disk, not injected."""

    entry_id: str
    hits: int
    misses: int
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
