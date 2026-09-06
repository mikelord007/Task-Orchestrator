"""Append a lesson to ``playbook/lessons.jsonl``, mirror it into the ``lessons``
table, and emit ``lesson_recorded`` -- unless it is a near-duplicate of one
already recorded (contracts/playbook.md rules 1 and 4: append-only, recorded
only from an accepted fix, never rewritten).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from backend.architect.playbook_reader import read_lessons
from backend.db import utcnow
from backend.ledger.emit import emit

from .dedupe import find_near_duplicate

DEFAULT_PLAYBOOK_PATH = "playbook/lessons.jsonl"

__all__ = ["DEFAULT_PLAYBOOK_PATH", "new_lesson_id", "record_lesson"]


def new_lesson_id() -> str:
    return f"lesson_{uuid.uuid4().hex[:8]}"


def _mirror_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        'INSERT OR IGNORE INTO lessons '
        '(id, lever, "trigger", lesson, domain_tags, source_agent_id, source_issue_id, ts) '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row["lever"],
            row["trigger"],
            row["lesson"],
            json.dumps(row["domain_tags"]),
            row["source_agent_id"],
            row["source_issue_id"],
            row["ts"],
        ),
    )


def record_lesson(
    *,
    lever: str,
    trigger: str,
    lesson: str,
    domain_tags: list[str],
    source_agent_id: str,
    source_issue_id: str | None = None,
    agent_version: int | None = None,
    playbook_path: str | Path = DEFAULT_PLAYBOOK_PATH,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Append the lesson and emit ``lesson_recorded``; ``None`` if skipped as a
    near-duplicate (rule §7 of the brief: normalized similarity >= 0.85,
    difflib, no embeddings). The ledger event and the sqlite mirror are only
    written when ``conn`` is given -- a caller building the jsonl file offline
    (e.g. a script with no ledger open) can pass ``conn=None``.
    """
    path = Path(playbook_path)
    existing = read_lessons(path)
    candidate = {"trigger": trigger, "lesson": lesson}
    if find_near_duplicate(candidate, existing) is not None:
        return None

    row = {
        "id": new_lesson_id(),
        "lever": lever,
        "trigger": trigger,
        "lesson": lesson,
        "domain_tags": list(domain_tags),
        "source_agent_id": source_agent_id,
        "source_issue_id": source_issue_id,
        "ts": utcnow(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")

    if conn is not None:
        _mirror_row(conn, row)
        conn.commit()
        emit(
            "lesson_recorded",
            agent_id=source_agent_id,
            agent_version=agent_version,
            lever=lever,
            conn=conn,
            payload={
                "lesson_id": row["id"],
                "trigger": trigger,
                "lesson": lesson,
                "source_agent_id": source_agent_id,
                "source_issue_id": source_issue_id,
            },
        )

    return row
