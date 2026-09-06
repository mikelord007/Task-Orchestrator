from __future__ import annotations

import json

from backend.ledger.emit import read as read_events
from backend.playbook.record import record_lesson


def test_record_lesson_appends_to_the_jsonl_file(tmp_path, conn):
    path = tmp_path / "lessons.jsonl"
    row = record_lesson(
        lever="memory",
        trigger="agent must map free-text input to a fixed label vocabulary",
        lesson="Write one rule per label with the evidence case ids.",
        domain_tags=["classification", "triage"],
        source_agent_id="a_github_triage_1",
        source_issue_id=None,
        agent_version=1,
        playbook_path=path,
        conn=conn,
    )
    assert row is not None
    assert row["lever"] == "memory"
    assert row["id"].startswith("lesson_")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk == row


def test_record_lesson_mirrors_into_the_lessons_table(tmp_path, conn):
    path = tmp_path / "lessons.jsonl"
    row = record_lesson(
        lever="tools",
        trigger="an agent's tool call is rejected for an invalid parameter",
        lesson="Rewrite the tool's error message to show a valid example call.",
        domain_tags=["tool_use"],
        source_agent_id="a_1",
        playbook_path=path,
        conn=conn,
    )
    db_row = conn.execute("SELECT * FROM lessons WHERE id = ?", (row["id"],)).fetchone()
    assert db_row is not None
    assert db_row["lever"] == "tools"
    assert json.loads(db_row["domain_tags"]) == ["tool_use"]


def test_record_lesson_emits_lesson_recorded(tmp_path, conn):
    path = tmp_path / "lessons.jsonl"
    row = record_lesson(
        lever="prompt",
        trigger="agent omits secondary labels it is unsure about",
        lesson="Instruct the agent to list every label it considered, not just the top one.",
        domain_tags=["classification"],
        source_agent_id="a_1",
        source_issue_id="i9",
        agent_version=2,
        playbook_path=path,
        conn=conn,
    )
    events = read_events(kind="lesson_recorded", agent_id="a_1", conn=conn)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["lesson_id"] == row["id"]
    assert payload["source_issue_id"] == "i9"
    assert events[0]["lever"] == "prompt"


def test_record_lesson_skips_a_near_duplicate_without_writing_anything(tmp_path, conn):
    path = tmp_path / "lessons.jsonl"
    first = record_lesson(
        lever="memory",
        trigger="agent must map free-text reports to a fixed label vocabulary",
        lesson="Write one rule per label describing the signal that selects it.",
        domain_tags=["classification"],
        source_agent_id="a_1",
        playbook_path=path,
        conn=conn,
    )
    assert first is not None

    duplicate = record_lesson(
        lever="memory",
        trigger="agent must map free text reports to a fixed label vocabulary",
        lesson="Write one rule per label describing the signal that selects it.",
        domain_tags=["classification"],
        source_agent_id="a_2",
        playbook_path=path,
        conn=conn,
    )
    assert duplicate is None

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # nothing appended for the duplicate

    events = read_events(kind="lesson_recorded", conn=conn)
    assert len(events) == 1  # no second event emitted


def test_record_lesson_without_a_connection_still_writes_the_file(tmp_path):
    path = tmp_path / "lessons.jsonl"
    row = record_lesson(
        lever="memory",
        trigger="agent must map free-text input to a fixed label vocabulary",
        lesson="Write one rule per label.",
        domain_tags=[],
        source_agent_id="a_1",
        playbook_path=path,
        conn=None,
    )
    assert row is not None
    assert path.read_text(encoding="utf-8").strip()
