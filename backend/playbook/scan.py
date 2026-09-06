"""Scan ``fix_accepted`` events and record transferable playbook lessons.

``scan()`` remains the caller-owned cursor API. ``scan_and_record()`` is the
production hook: it reads and persists a processing cursor so serial callers
can incrementally process accepted fixes in one call.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.architect.llm_client import CompleteFn
from backend.db import REPO_ROOT
from backend.ledger.query import Event, events
from backend.settings import env

from .extract import LessonExtractionError, extract_lesson
from .record import DEFAULT_PLAYBOOK_PATH, record_lesson

__all__ = ["ScanResult", "scan", "scan_and_record"]

_SCAN_CURSOR_KEY = "fix_accepted"


@dataclass
class ScanResult:
    """Recorded/skipped events and the exclusive watermark from one scan."""

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

    A duplicate is terminal and advances the result watermark. A
    ``fix_accepted`` with no matching ``fix_proposed`` or an extraction that
    raises :class:`~backend.playbook.extract.LessonExtractionError` is
    retryable: its id is added to ``skipped_unusable_event_ids`` and scanning
    stops without advancing past it.
    """
    result = ScanResult(last_event_id=since_event_id)
    accepted_events = [e for e in events(conn, kind="fix_accepted") if e.id > since_event_id]

    for accepted in accepted_events:
        proposed = _fix_proposed_for(conn, accepted)
        if proposed is None:
            result.skipped_unusable_event_ids.append(accepted.id)
            break

        fix_card = _fix_card(accepted, proposed)
        try:
            extracted, _response = extract_lesson(fix_card, complete=complete, model=model)
        except LessonExtractionError:
            result.skipped_unusable_event_ids.append(accepted.id)
            break

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
        result.last_event_id = max(result.last_event_id, accepted.id)

    return result


def _persisted_watermark(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT last_event_id FROM playbook_scan_cursors WHERE stream = ?",
        (_SCAN_CURSOR_KEY,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _save_watermark(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute(
        """
        INSERT INTO playbook_scan_cursors (stream, last_event_id)
        VALUES (?, ?)
        ON CONFLICT(stream) DO UPDATE SET
          last_event_id = MAX(playbook_scan_cursors.last_event_id, excluded.last_event_id)
        """,
        (_SCAN_CURSOR_KEY, event_id),
    )
    conn.commit()


def _configured_playbook_path() -> Path:
    return Path(env("TO_PLAYBOOK_PATH") or REPO_ROOT / "playbook" / "lessons.jsonl")


def scan_and_record(
    conn: sqlite3.Connection,
    *,
    since_event_id: int | None = None,
    playbook_path: str | Path | None = None,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> ScanResult:
    """Scan accepted fixes and persist the cursor for the next invocation.

    ``None`` resumes from the cursor stored in ``playbook_scan_cursors``. An
    explicit cursor overrides the stored starting point for this call. The
    stored cursor advances only after :func:`scan` returns successfully and
    never moves backward.
    """
    persisted = _persisted_watermark(conn)
    watermark = persisted if since_event_id is None else since_event_id
    resolved_playbook_path = _configured_playbook_path() if playbook_path is None else playbook_path

    result = scan(
        conn,
        since_event_id=watermark,
        playbook_path=resolved_playbook_path,
        complete=complete,
        model=model,
    )
    highest_observed_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
    _save_watermark(conn, min(result.last_event_id, int(highest_observed_id)))
    return result
