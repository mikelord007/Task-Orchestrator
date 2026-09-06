"""Diagnose: rank the top-3 train failure groups and hypothesize a fix for
each (PLAN_ADDENDUM.md sections D and K).

`diagnose(agent_id, version)` makes one STRONG call per group (top-3 by
failing-trial count) over the group's transcripts and `tool_call_stats`, and
returns a `Diagnosis` per group recommending a lever. Lever preference is
`memory -> tools -> prompt -> orchestration` (section E); a `tools` diagnosis
must cite a tracked-metric `metric_signal` (section K) or it is rejected by
`validate_diagnosis` below, and a `drift:*` group must resolve to `tools` or
`prompt` (a drift is a tool/instruction problem, not a knowledge gap memory
can fix, and not something changing orchestration mode addresses).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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
    "validate_diagnosis",
]

MAX_GROUPS = 3
MAX_CASES_SHOWN = 5
MAX_FIELD_CHARS = 400
_VALID_LEVERS = {lever.value for lever in Lever}
_DRIFT_LEVERS = {Lever.tools.value, Lever.prompt.value}


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
    if diagnosis.lever == Lever.tools.value and not (diagnosis.metric_signal or "").strip():
        raise DiagnosisValidationError(
            "lever=tools diagnosis has no metric_signal; section K requires the "
            "tracked-metric heuristic that drove the diagnosis (e.g. redundant-call "
            "count or invalid-parameter error rate)"
        )
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


def _diagnosis_prompt(
    agent_id: str,
    version: int,
    group: FailingGroup,
    evidence: str,
    stats: dict[str, Any],
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
        "error rate from the tool stats below) -> prompt (the system prompt is "
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
        f"Tool usage stats -- `group_tasks` is per failing task in this group, "
        f"`run_aggregate` is the whole train run for scale: {stats}\n\n"
        f"Evidence:\n{evidence or '(no transcripts available)'}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _coerce_diagnosis(group: FailingGroup, parsed: dict[str, Any]) -> Diagnosis:
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
) -> list[Diagnosis]:
    """Top-`MAX_GROUPS` train failure groups, each with one recommended fix."""
    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)
    try:
        evaluator_path = resolve_evaluator_path(conn, agent_id)
        groups = group_train_failures(conn, agent_id, version, evaluator_path)[:MAX_GROUPS]
        if not groups:
            return []
        case_index = load_case_index(evaluator_path)
        run_stats = tool_call_stats(conn, agent_id, version, "train", root)

        resolved_model = model or _default_model()
        diagnoses: list[Diagnosis] = []
        for group in groups:
            evidence = _render_group_evidence(conn, agent_id, version, group, case_index, root)
            messages = _diagnosis_prompt(
                agent_id, version, group, evidence, _group_tool_stats(run_stats, group)
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
            diagnoses.append(_coerce_diagnosis(group, parsed))
        return diagnoses
    finally:
        if owns_conn:
            conn.close()


def _default_model() -> str:
    from backend import llm

    return str(llm.MODEL_STRONG)
