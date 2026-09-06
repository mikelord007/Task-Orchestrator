"""Diagnose: rank the top-3 train failure groups and hypothesize a fix for
each (PLAN_ADDENDUM.md sections D and K).

`diagnose(agent_id, version)` makes one STRONG call per group (top-3 by
failing-trial count) over the group's transcripts and `tool_call_stats`, and
returns a `Diagnosis` per group recommending a lever. Lever preference is
`memory -> tools -> prompt -> orchestration` (section E); a `tools` diagnosis
must cite a tracked-metric `metric_signal` (section K) *and* that signal is
checked against `observed_tool_usage` -- what the harness actually recorded
on the group's failing trials -- so an invented number never reaches the
append-only ledger; either failure is rejected by `validate_diagnosis`
below. A `drift:*` group must resolve to `tools` or `prompt` (a drift is a
tool/instruction problem, not a knowledge gap memory can fix, and not
something changing orchestration mode addresses).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.architect.llm_client import CompleteFn
from backend.improver.grouping import (
    failing_case_trials,
    group_train_failures,
    load_case_index,
    resolve_evaluator_path,
    resolve_transcript_path,
)
from backend.improver.json_llm import JsonCallError, complete_json
from backend.ledger.metrics import tool_call_stats
from contracts.events import FailingGroup, Lever
from contracts.transcript import load_transcript

__all__ = [
    "MAX_GROUPS",
    "Diagnosis",
    "DiagnosisValidationError",
    "diagnose",
    "metric_signal_problem",
    "observed_tool_usage",
    "validate_diagnosis",
]

MAX_GROUPS = 3
MAX_CASES_SHOWN = 5
MAX_FIELD_CHARS = 400
_VALID_LEVERS = {lever.value for lever in Lever}
_DRIFT_LEVERS = {Lever.tools.value, Lever.prompt.value}

#: A token in a `metric_signal` that claims to name a tool. Every tool in this
#: project is snake_case (`lookup_ticket`, `github_get_issue_context`), and
#: prose about a metric is not, so the underscore is what separates "the model
#: named a tool" from "the model wrote a sentence".
_TOOL_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")

#: Claim words in a `metric_signal`, and the observed counter each one has to
#: be backed by. A signal that talks about errors when the harness recorded
#: none is a fabricated number, not a diagnosis.
_CLAIM_COUNTERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("error", "invalid", "failed", "failure"), "errors"),
    (("redundant", "repeat", "duplicate", "again", "over and over"), "redundant"),
)


class DiagnosisValidationError(ValueError):
    """A parsed diagnosis violates section K/E's rules."""


@dataclass
class Diagnosis:
    """One group's recommended fix. `hypothesis` is the ≤3-sentence, judge-
    readable explanation; `diagnosis` is the (also short) technical read that
    goes verbatim into the `fix_proposed.diagnosis` field."""

    failing_group: FailingGroup
    hypothesis: str
    diagnosis: str
    lever: str
    proposed_change: str
    metric_signal: str | None = None
    issue_id: str | None = None
    observed_tool_usage: dict[str, dict[str, float]] = field(default_factory=dict)
    """Per-tool calls/errors/redundant counts the harness actually recorded on
    this group's failing trials. This is the ground truth `metric_signal` is
    checked against, and `patch` copies it onto `fix_proposed.extra` so the
    ledger holds the observation next to the model's claim about it."""


def metric_signal_problem(metric_signal: str, observed: dict[str, dict[str, float]]) -> str | None:
    """How `metric_signal` contradicts what the harness recorded, or `None`.

    Section K asks a tools diagnosis to *cite* a tracked metric. Left
    unchecked that is just a sentence the model wrote, and `patch` appends it
    permanently to `fix_proposed` as if it were a measurement -- exactly the
    fabricated number section 0 forbids. So the claim is held to the
    observation:

    * it must name a tool this group's failing trials actually called, and
    * a claim *about* errors or redundant calls must be backed by a non-zero
      count of them.

    With no observation to check against (`observed` empty -- no readable
    transcripts) the signal is let through: refusing every tools fix because
    the evidence is missing would be its own kind of dishonesty.
    """
    if not observed:
        return None

    named = _TOOL_TOKEN.findall(metric_signal)
    unknown = sorted({t for t in named if t not in observed})
    if unknown:
        return (
            f"metric_signal names {unknown}, which made no tool call on this group's "
            f"failing trials; the harness observed {sorted(observed)}"
        )
    if not any(tool in observed for tool in named):
        return (
            f"metric_signal names none of the tools observed on this group's failing "
            f"trials ({sorted(observed)}), so there is nothing to check it against"
        )

    lowered = metric_signal.lower()
    cited = [tool for tool in named if tool in observed]
    for words, counter in _CLAIM_COUNTERS:
        if not any(word in lowered for word in words):
            continue
        total = sum(observed[tool].get(counter, 0.0) for tool in cited)
        if total <= 0:
            return (
                f"metric_signal claims {counter} for {cited}, but the harness recorded "
                f"{counter}=0 on this group's failing trials"
            )
    return None


def validate_diagnosis(diagnosis: Diagnosis) -> None:
    """Raise `DiagnosisValidationError` if `diagnosis` violates section K/E.

    - `lever` must be one of the contract's `Lever` values.
    - `lever == "tools"` must carry a non-empty `metric_signal` (section K:
      "each tools diagnosis must cite the tracked-metric signal").
    - a `drift:*` failing group must resolve to `tools` or `prompt`.
    """
    if diagnosis.lever not in _VALID_LEVERS:
        raise DiagnosisValidationError(
            f"unknown lever {diagnosis.lever!r}; expected one of {sorted(_VALID_LEVERS)}"
        )
    if diagnosis.lever == Lever.tools.value:
        signal = (diagnosis.metric_signal or "").strip()
        if not signal:
            raise DiagnosisValidationError(
                "lever=tools diagnosis has no metric_signal; section K requires the "
                "tracked-metric heuristic that drove the diagnosis (e.g. redundant-call "
                "count or invalid-parameter error rate)"
            )
        problem = metric_signal_problem(signal, diagnosis.observed_tool_usage)
        if problem is not None:
            raise DiagnosisValidationError(problem)
    is_drift = diagnosis.failing_group.signature.startswith("drift:")
    if is_drift and diagnosis.lever not in _DRIFT_LEVERS:
        raise DiagnosisValidationError(
            f"drift group {diagnosis.failing_group.signature!r} must resolve to "
            f"lever=tools or lever=prompt, got {diagnosis.lever!r}"
        )


def _truncate(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    import json

    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _render_group_evidence(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    group: FailingGroup,
    case_index: dict[str, dict[str, Any]],
    root: str | Path,
) -> str:
    trials = failing_case_trials(
        conn, agent_id, version, set(group.case_ids), max_cases=MAX_CASES_SHOWN
    )
    lines: list[str] = []
    for case_id, trial, transcript_path in trials:
        full_path = resolve_transcript_path(root, transcript_path)
        try:
            transcript = load_transcript(full_path)
        except (OSError, ValueError):
            continue
        result = getattr(transcript, "result", None) or {}
        notes = result.get("notes") if isinstance(result, dict) else None
        case_row = case_index.get(case_id, {})
        lines.append(
            f"- {case_id} (trial {trial}): expected={_truncate(case_row.get('expected'))} "
            f"got={_truncate(transcript.final_output)} notes={notes or '(none)'}"
        )
    return "\n".join(lines)


def observed_tool_usage(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    group: FailingGroup,
    root: str | Path,
) -> dict[str, dict[str, float]]:
    """Per-tool `calls`/`errors`/`redundant` counts on this group's failing
    trials, read straight from the harness-recorded transcripts.

    `ledger.metrics.tool_call_stats` aggregates across every tool, which is
    the right shape for a run-level chart and the wrong one for checking a
    claim about *a* tool. A redundant call is the same tool with identical
    arguments seen again inside one trial (PLAN_ADDENDUM.md section K).
    """
    usage: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0.0, "errors": 0.0, "redundant": 0.0}
    )
    for _case_id, _trial, transcript_path in failing_case_trials(
        conn, agent_id, version, set(group.case_ids), max_cases=MAX_CASES_SHOWN
    ):
        try:
            transcript = load_transcript(resolve_transcript_path(root, transcript_path))
        except (OSError, ValueError):
            continue
        seen: set[str] = set()
        steps = transcript.steps
        for i, step in enumerate(steps):
            kind = step.kind.value if hasattr(step.kind, "value") else step.kind
            if kind != "tool_call" or not step.tool:
                continue
            counts = usage[str(step.tool)]
            counts["calls"] += 1
            key = f"{step.tool}:{json.dumps(step.args or {}, sort_keys=True, default=str)}"
            if key in seen:
                counts["redundant"] += 1
            seen.add(key)
            following = steps[i + 1] if i + 1 < len(steps) else None
            if following is not None and following.error:
                following_kind = (
                    following.kind.value if hasattr(following.kind, "value") else following.kind
                )
                if following_kind == "tool_return":
                    counts["errors"] += 1
    return dict(usage)


def _group_tool_stats(stats: dict[str, Any], group: FailingGroup) -> dict[str, Any]:
    """This group's own per-task tool usage, plus the run aggregate for scale.

    Section K asks a `tools` diagnosis to cite a tracked metric about *these*
    tasks. The run-wide aggregate alone is diluted by every task that passed:
    a group whose three failing tasks each make three redundant calls reads
    as "0.5 redundant calls" across a run of six executions, which is not a
    signal anyone should act on. Both are shown, labelled, so the model can
    say "4.2 on the failing tasks vs 0.3 across the run".
    """
    tasks = stats.get("tasks") or {}
    return {
        "group_tasks": {case_id: tasks[case_id] for case_id in group.case_ids if case_id in tasks},
        "run_aggregate": stats.get("aggregate") or {},
    }


def _render_reflection(proposals: list[Any]) -> str:
    """The reflection step's proposals for this group, as prose the analyst
    can weigh. They are proposals, not findings: nothing here is accepted
    until `patch` writes it and `gate` keeps the version holding it."""
    lines: list[str] = []
    for proposal in proposals:
        cited = ", ".join(proposal.evidence_case_ids) or "(none)"
        if proposal.kind == "rule":
            lines.append(f"- rule (from {cited}): {proposal.rule}")
        else:
            lines.append(f"- tool note on {proposal.tool} (from {cited}): {proposal.note}")
    return "\n".join(lines)


def _diagnosis_prompt(
    agent_id: str,
    version: int,
    group: FailingGroup,
    evidence: str,
    stats: dict[str, Any],
    reflection: list[Any] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are the failure-analyst step of an agent-improvement harness. You are "
        "shown one failure group -- tasks that failed the grader, grouped by a "
        "normalized failure signature -- for one version of an agent, using only "
        "harness-recorded transcripts and tracked tool-usage metrics (never the "
        "agent's own account of what happened; pass/fail already came from the "
        "grader). Diagnose the root cause and recommend exactly one lever to fix it.\n\n"
        "Lever preference order, cheapest and most targeted first: memory (a "
        "missing rule or tool note would have prevented this) -> tools (the tool's "
        "description, defaults, or error messages mislead the agent -- you MUST "
        "then cite metric_signal, e.g. a redundant-call count or invalid-parameter "
        "error rate from `observed_tool_usage` below, naming the tool and quoting "
        "its recorded number -- a signal that names a tool the group never called, "
        "or claims errors or redundant calls the harness recorded as zero, is "
        "rejected and the fix is downgraded) -> prompt (the system prompt is "
        "ambiguous or missing an instruction) -> orchestration (the single-agent "
        "loop itself is the wrong shape for this task). A failure signature "
        "starting with 'drift:' is a tool-use loop or a prompt that failed to make "
        "the agent stop and answer -- it can only be diagnosed as lever=tools or "
        "lever=prompt, never memory or orchestration.\n\n"
        'Return ONLY a JSON object: {"hypothesis": str (<=3 plain sentences a judge '
        'can read aloud), "diagnosis": str (<=3 sentences, technical), '
        '"lever": "memory"|"tools"|"prompt"|"orchestration", '
        '"metric_signal": str or null, "proposed_change": str (concrete, one lever\'s '
        "worth of change)}."
    )
    user = (
        f"Agent: {agent_id} v{version}\n"
        f"Failing group: signature={group.signature!r} tag={group.tag!r} "
        f"({group.count} failing trial(s) across {len(group.case_ids)} task(s))\n\n"
        f"Tool usage stats -- `observed_tool_usage` is per tool on this group's "
        f"failing trials (the ONLY numbers a metric_signal may cite), "
        f"`group_tasks` is per failing task, `run_aggregate` is the whole train "
        f"run for scale: {stats}\n\n"
        f"Evidence:\n{evidence or '(no transcripts available)'}\n\n"
        f"Reflection already proposed, for this group, the following durable "
        f"lessons (proposals, not findings -- weigh them, and prefer lever=memory "
        f"if writing one of them down would have prevented these failures):\n"
        f"{_render_reflection(reflection or []) or '(reflection proposed nothing)'}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _coerce_diagnosis(
    group: FailingGroup,
    parsed: dict[str, Any],
    observed: dict[str, dict[str, float]] | None = None,
) -> Diagnosis:
    lever = str(parsed.get("lever") or "").strip()
    metric_signal = parsed.get("metric_signal")
    metric_signal = str(metric_signal).strip() if metric_signal else None
    diagnosis = Diagnosis(
        failing_group=group,
        hypothesis=str(parsed.get("hypothesis") or "").strip() or "No hypothesis produced.",
        diagnosis=str(parsed.get("diagnosis") or "").strip() or "No diagnosis produced.",
        lever=lever,
        proposed_change=str(parsed.get("proposed_change") or "").strip(),
        metric_signal=metric_signal,
        observed_tool_usage=observed or {},
    )
    try:
        validate_diagnosis(diagnosis)
    except DiagnosisValidationError as exc:
        # Fall back to lever=prompt rather than dropping the group: it is
        # always a valid choice (never rejected by validate_diagnosis) and
        # keeps `diagnose` returning one entry per top group as documented.
        diagnosis.lever = Lever.prompt.value
        diagnosis.metric_signal = None
        diagnosis.diagnosis = (diagnosis.diagnosis + f" (forced lever=prompt: {exc})").strip()
    return diagnosis


def diagnose(
    agent_id: str,
    version: int,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    root: str | Path = ".",
    model: str | None = None,
    complete: CompleteFn | None = None,
    groups: list[FailingGroup] | None = None,
    reflections: dict[str, list[Any]] | None = None,
) -> list[Diagnosis]:
    """Top-`MAX_GROUPS` train failure groups, each with one recommended fix.

    `improve` reflects before it diagnoses (section E), so it passes the
    `groups` it already computed and the `reflections` those groups produced;
    the agent's own reading of the failure is then part of what the analyst
    weighs. Called on its own, `diagnose` groups the failures itself and the
    analyst simply sees no reflection.
    """
    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)
    try:
        evaluator_path = resolve_evaluator_path(conn, agent_id)
        if groups is None:
            groups = group_train_failures(conn, agent_id, version, evaluator_path)
        groups = groups[:MAX_GROUPS]
        if not groups:
            return []
        case_index = load_case_index(evaluator_path)
        run_stats = tool_call_stats(conn, agent_id, version, "train", root)

        resolved_model = model or _default_model()
        diagnoses: list[Diagnosis] = []
        for group in groups:
            evidence = _render_group_evidence(conn, agent_id, version, group, case_index, root)
            observed = observed_tool_usage(conn, agent_id, version, group, root)
            stats = {
                "observed_tool_usage": observed,
                **_group_tool_stats(run_stats, group),
            }
            messages = _diagnosis_prompt(
                agent_id,
                version,
                group,
                evidence,
                stats,
                (reflections or {}).get(group.signature) or [],
            )
            try:
                parsed, _response = complete_json(messages, resolved_model, complete=complete)
            except JsonCallError:
                parsed = {
                    "hypothesis": "The model did not return a usable diagnosis for this group.",
                    "diagnosis": "LLM call failed to produce JSON; defaulting to a prompt fix.",
                    "lever": Lever.prompt.value,
                    "proposed_change": "Clarify the output format instruction in prompt.md.",
                }
            diagnoses.append(_coerce_diagnosis(group, parsed, observed))
        return diagnoses
    finally:
        if owns_conn:
            conn.close()


def _default_model() -> str:
    from backend import llm

    return str(llm.MODEL_STRONG)
