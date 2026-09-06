"""Scan the ledger for ``fix_accepted`` events not yet distilled into a lesson.

W6's improver is not merged yet (PLAN.md 7, W8 brief), so nothing calls this
automatically today. ``scan()`` is the hook it -- or a cron/script -- calls:
"a CHEAP-model call extracts one lesson on every ``fix_accepted``" (brief §1)
becomes "on every ``fix_accepted`` newer than ``since_event_id``". The caller
owns the watermark (persisting the returned ``last_event_id`` and passing it
back next time); this module keeps no cursor of its own, matching the
ledger's read-only-consumer contract (``backend/ledger/query.py``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.architect.llm_client import CompleteFn
from backend.ledger.query import Event, events

from .extract import LessonExtractionError, extract_lesson
from .record import DEFAULT_PLAYBOOK_PATH, record_lesson

__all__ = ["ScanResult", "scan"]


@dataclass
class ScanResult:
    """What one ``scan()`` call did, so a caller can persist the watermark."""

    lessons: list[dict[str, Any]] = field(default_factory=list)
    skipped_duplicate_event_ids: list[int] = field(default_factory=list)
    skipped_unusable_event_ids: list[int] = field(default_factory=list)
    last_event_id: int = 0


def _fix_proposed_for(conn: sqlite3.Connection, accepted: Event) -> Event | None:
    """The ``fix_proposed`` this ``fix_accepted`` answers (same agent + ``to_version``).

    If two proposals ever targeted the same ``to_version``, the newest one
    wins -- mirrors ``backend.ledger.metrics._proposals_by_version``.
    """
    to_version = accepted.get("to_version")
    if to_version is None or accepted.agent_id is None:
        return None
    candidates = [
        e
        for e in events(conn, kind="fix_proposed", agent_id=accepted.agent_id)
        if e.get("to_version") == to_version
    ]
    return candidates[-1] if candidates else None


def _fix_card(accepted: Event, proposed: Event) -> dict[str, Any]:
    """The slice of a fix card :mod:`extract` needs: hypothesis, diagnosis,
    diff summary and before/after numbers -- never the agent's own words."""
    return {
        "lever": proposed.lever or proposed.get("lever"),
        "hypothesis": proposed.get("hypothesis"),
        "diagnosis": proposed.get("diagnosis"),
        "diff_summary": proposed.get("diff_summary"),
        "metric_signal": proposed.get("metric_signal"),
        "before": {
            "pass_at_1": accepted.get("pass_at_1_before"),
            "pass_pow_k": accepted.get("pass_pow_k_before"),
            "group_pass": accepted.get("group_pass_before"),
            "cost_per_run": accepted.get("cost_per_run_before"),
            "tool_calls_per_task": accepted.get("tool_calls_per_task_before"),
        },
        "after": {
            "pass_at_1": accepted.get("pass_at_1_after"),
            "pass_pow_k": accepted.get("pass_pow_k_after"),
            "group_pass": accepted.get("group_pass_after"),
            "holdout_pass_at_1": accepted.get("holdout_pass_at_1_after"),
            "holdout_pass_pow_k": accepted.get("holdout_pass_pow_k_after"),
            "cost_per_run": accepted.get("cost_per_run_after"),
            "tool_calls_per_task": accepted.get("tool_calls_per_task_after"),
        },
    }


def scan(
    conn: sqlite3.Connection,
    *,
    since_event_id: int = 0,
    playbook_path: str | Path = DEFAULT_PLAYBOOK_PATH,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> ScanResult:
    """Extract and record one lesson per new ``fix_accepted`` event.

    A ``fix_accepted`` with no matching ``fix_proposed`` (should not happen in
    practice, but the ledger makes no such guarantee) is skipped, not fatal --
    one bad row must not stop the rest of the scan. Likewise an extraction
    that raises :class:`~backend.playbook.extract.LessonExtractionError` is
    recorded as skipped and the scan continues.
    """
    result = ScanResult(last_event_id=since_event_id)
    accepted_events = [e for e in events(conn, kind="fix_accepted") if e.id > since_event_id]

    for accepted in accepted_events:
        result.last_event_id = max(result.last_event_id, accepted.id)
        proposed = _fix_proposed_for(conn, accepted)
        if proposed is None:
            continue

        fix_card = _fix_card(accepted, proposed)
        try:
            extracted, _response = extract_lesson(fix_card, complete=complete, model=model)
        except LessonExtractionError:
            result.skipped_unusable_event_ids.append(accepted.id)
            continue

        recorded = record_lesson(
            lever=extracted["lever"],
            trigger=extracted["trigger"],
            lesson=extracted["lesson"],
            domain_tags=extracted["domain_tags"],
            source_agent_id=accepted.agent_id,
            source_issue_id=proposed.get("issue_id"),
            agent_version=accepted.agent_version,
            playbook_path=playbook_path,
            conn=conn,
        )
        if recorded is None:
            result.skipped_duplicate_event_ids.append(accepted.id)
        else:
            result.lessons.append(recorded)

    return result
