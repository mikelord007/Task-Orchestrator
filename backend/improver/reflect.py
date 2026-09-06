"""Reflection: the agent's own analysis of one failure group (PLAN_ADDENDUM.md
sections E and 0).

`reflect(agent_id, version, failure_group)` makes exactly one STRONG LLM call
over harness-recorded evidence only: the group's transcripts (every request,
response, tool call and tool return the runtime observed), the grader's
verdict -- `passed`, `score` and the notes -- and the evaluator's `expected`
output. It is the first step of `improve`, run on every top failure group
before anything is diagnosed. The prompt
below contains, verbatim, the sentence PLAN_ADDENDUM.md section E mandates:
the model is never asked whether it succeeded, and its output is a proposal
-- accepted into memory only if `patch` writes it and `gate` later keeps the
version that holds it.

Output is capped at 3 rule proposals + 2 tool-note proposals per group, and
every rule's `evidence_case_ids` is filtered down to ids that are actually in
`failure_group.case_ids` -- a rule cannot cite evidence from outside the
group it was reflected from. Matching is by whole token, so a group holding
`t1` does not silently claim `t10` as its evidence.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from backend.architect.llm_client import CompleteFn
from backend.improver.grouping import (
    failing_case_trials,
    load_case_index,
    resolve_evaluator_path,
    resolve_transcript_path,
)
from backend.improver.json_llm import JsonCallError, complete_json
from contracts.events import FailingGroup
from contracts.transcript import Transcript, load_transcript

__all__ = [
    "MANDATE",
    "MAX_RULES",
    "MAX_TOOL_NOTES",
    "Proposal",
    "cited_case_ids",
    "reflect",
    "reflection_prompt",
]

#: PLAN_ADDENDUM.md section E's mandated sentence. Must appear verbatim.
MANDATE = (
    "Do not evaluate your own performance; the grade is given. Explain the "
    "discrepancy using only the transcript and tool data provided."
)

MAX_RULES = 3
MAX_TOOL_NOTES = 2
MAX_CASES_SHOWN = 5
MAX_FIELD_CHARS = 700

#: A case id as it appears inside free-text evidence. Ids are alphanumeric
#: with `_`/`-`, and the surrounding characters must not be, so `t1` does not
#: match inside `t10`.
_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


@dataclass
class Proposal:
    """One reflection proposal: a memory rule or a tool note.

    `kind` selects which fields are meaningful (`patch` writes rules to
    `rules.jsonl` and tool notes to `tool_notes.jsonl`); the unused fields for
    the other kind stay at their defaults.
    """

    kind: Literal["rule", "tool_note"]
    evidence_case_ids: list[str] = field(default_factory=list)
    rule: str | None = None
    scope_keywords: list[str] = field(default_factory=list)
    tool: str | None = None
    note: str | None = None
    evidence: str | None = None


def _truncate(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _render_transcript_tools(transcript: Transcript) -> list[str]:
    lines: list[str] = []
    for step in transcript.steps:
        kind = step.kind.value if hasattr(step.kind, "value") else step.kind
        if kind == "tool_call":
            lines.append(f"  CALL {step.tool}({_truncate(step.args)})")
        elif kind == "tool_return":
            label = "ERROR" if step.error is not None else "RETURN"
            body = step.error if step.error is not None else step.result
            lines.append(f"  {label} {step.tool}: {_truncate(body)}")
    return lines


def _grader_verdict(transcript: Transcript) -> str:
    """The grader's verdict on this trial, as the harness recorded it.

    `backend/runtime/transcript.py` writes `result = {passed, score, notes,
    ...}` onto every transcript. Reflection is shown all three: a task that
    failed at 0.79 and one that failed at 0.0 can carry near-identical notes,
    and proposing the same broad rule for both is exactly the mistake the
    score is there to prevent.
    """
    result = getattr(transcript, "result", None)
    if not isinstance(result, dict):
        return "(the harness recorded no grader verdict on this trial)"
    passed = result.get("passed")
    score = result.get("score")
    verdict = "PASSED" if passed else "FAILED"
    score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "unknown"
    notes = str(result.get("notes") or "").strip() or "(no notes)"
    return f"{verdict} at score {score_text} -- {notes}"


def _render_case_evidence(
    case_id: str, trial: int, transcript: Transcript, case_row: dict[str, Any]
) -> str:
    lines = [f"Case {case_id} (trial {trial}):"]
    lines.append(f"  Input: {_truncate(case_row.get('input'))}")
    lines.append(f"  Expected output: {_truncate(case_row.get('expected'))}")
    lines.append(f"  Agent's final output: {_truncate(transcript.final_output)}")
    lines.append(f"  Grader verdict: {_grader_verdict(transcript)}")
    tool_lines = _render_transcript_tools(transcript)
    if tool_lines:
        lines.append("  Tool activity:")
        lines.extend(tool_lines)
    return "\n".join(lines)


def _gather_evidence(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    failure_group: FailingGroup,
    root: str | Path,
) -> list[str]:
    evaluator_path = resolve_evaluator_path(conn, agent_id)
    case_index = load_case_index(evaluator_path)
    trials = failing_case_trials(
        conn, agent_id, version, set(failure_group.case_ids), max_cases=MAX_CASES_SHOWN
    )
    blocks: list[str] = []
    for case_id, trial, transcript_path in trials:
        full_path = resolve_transcript_path(root, transcript_path)
        try:
            transcript = load_transcript(full_path)
        except (OSError, ValueError):
            continue
        case_row = case_index.get(case_id, {})
        blocks.append(_render_case_evidence(case_id, trial, transcript, case_row))
    return blocks


def reflection_prompt(
    agent_id: str, version: int, failure_group: FailingGroup, evidence_blocks: list[str]
) -> list[dict[str, str]]:
    """The messages sent to the model. Exposed for tests that assert the
    mandated sentence is present verbatim."""
    system = (
        "You are the reflection step of an agent-improvement harness. You are shown "
        "exactly what one version of an agent did on tasks it failed, as recorded by "
        "the harness (never by the agent itself), and the grader's verdict on each. "
        f"{MANDATE}\n\n"
        "Propose durable lessons the next version of the agent should carry in its "
        "memory: rules (general instructions with keywords for when they apply) and "
        "tool notes (mechanics of a specific tool you can see it misused or "
        "misunderstood from the tool call/return data). Every proposal must cite the "
        "case id(s) in this group that are its evidence -- do not invent a lesson "
        "with no case backing it in what you were shown.\n\n"
        f"Return ONLY a JSON object: "
        f'{{"rules": [{{"rule": str, "scope_keywords": [str], "evidence_case_ids": [str]}}], '
        f'"tool_notes": [{{"tool": str, "note": str, "evidence": str}}]}}. '
        f"At most {MAX_RULES} rules and {MAX_TOOL_NOTES} tool_notes."
    )
    user = (
        f"Agent: {agent_id} v{version}\n"
        f"Failure group: signature={failure_group.signature!r} tag={failure_group.tag!r} "
        f"({failure_group.count} failing trial(s) across {len(failure_group.case_ids)} task(s))\n\n"
        + "\n\n".join(evidence_blocks)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def cited_case_ids(evidence: str, group_case_ids: set[str]) -> set[str]:
    """The group's case ids that `evidence` genuinely names.

    Whole-token matching, not substring: with a group containing `t1`, the
    sentence "t10 called the tool incorrectly" cites `t10`, not `t1`. A
    substring test would record `t1` as the evidence for a note about a case
    the model never mentioned -- false provenance on an append-only
    `memory_written` row.
    """
    tokens = set(_ID_TOKEN.findall(evidence))
    return tokens & group_case_ids


def _valid_rule(entry: Any, group_case_ids: set[str]) -> Proposal | None:
    if not isinstance(entry, dict):
        return None
    rule = str(entry.get("rule") or "").strip()
    if not rule:
        return None
    evidence = [str(c) for c in (entry.get("evidence_case_ids") or []) if str(c) in group_case_ids]
    if not evidence:
        return None
    keywords = [str(k) for k in (entry.get("scope_keywords") or []) if str(k).strip()]
    return Proposal(kind="rule", rule=rule, scope_keywords=keywords, evidence_case_ids=evidence)


def _valid_tool_note(entry: Any, group_case_ids: set[str]) -> Proposal | None:
    if not isinstance(entry, dict):
        return None
    tool = str(entry.get("tool") or "").strip()
    note = str(entry.get("note") or "").strip()
    evidence = str(entry.get("evidence") or "").strip()
    if not tool or not note or not evidence:
        return None
    # Evidence must actually mention a case from this group -- "each citing
    # evidence case ids from the group" applies to tool notes too, even
    # though ToolNote.evidence is free text rather than a list.
    cited = sorted(cited_case_ids(evidence, group_case_ids))
    if not cited:
        return None
    return Proposal(
        kind="tool_note", tool=tool, note=note, evidence=evidence, evidence_case_ids=cited
    )


def reflect(
    agent_id: str,
    version: int,
    failure_group: FailingGroup,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    root: str | Path = ".",
    model: str | None = None,
    complete: CompleteFn | None = None,
) -> list[Proposal]:
    """One STRONG call: propose rules/tool-notes for `failure_group`.

    Returns at most `MAX_RULES` rule proposals and `MAX_TOOL_NOTES` tool-note
    proposals, each with evidence filtered to `failure_group.case_ids`. A
    group with no readable transcripts (nothing on disk yet) returns `[]`
    rather than calling the model with no evidence to reflect on.
    """
    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)
    try:
        evidence_blocks = _gather_evidence(conn, agent_id, version, failure_group, root)
    finally:
        if owns_conn:
            conn.close()

    if not evidence_blocks:
        return []

    messages = reflection_prompt(agent_id, version, failure_group, evidence_blocks)
    resolved_model = model or _default_model()

    try:
        parsed, _response = complete_json(messages, resolved_model, complete=complete)
    except JsonCallError:
        return []

    group_case_ids = set(failure_group.case_ids)
    rules = [
        p
        for entry in (parsed.get("rules") or [])[: MAX_RULES + 5]
        if (p := _valid_rule(entry, group_case_ids)) is not None
    ][:MAX_RULES]
    notes = [
        p
        for entry in (parsed.get("tool_notes") or [])[: MAX_TOOL_NOTES + 5]
        if (p := _valid_tool_note(entry, group_case_ids)) is not None
    ][:MAX_TOOL_NOTES]
    return rules + notes


def _default_model() -> str:
    from backend import llm

    return str(llm.MODEL_STRONG)
