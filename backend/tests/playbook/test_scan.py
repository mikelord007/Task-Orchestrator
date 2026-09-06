from __future__ import annotations

import importlib
import json

import pytest

from backend.ledger.emit import emit
from backend.playbook import scan_and_record
from backend.playbook.scan import scan

AGENT_ID = "agent_demo"


def _seed_fix(conn, *, to_version: int, issue_id: str | None = None) -> None:
    emit(
        "fix_proposed",
        agent_id=AGENT_ID,
        agent_version=to_version - 1,
        lever="memory",
        conn=conn,
        from_version=to_version - 1,
        to_version=to_version,
        issue_id=issue_id,
        failing_group={
            "signature": "wrong_component",
            "tag": "windows",
            "case_ids": ["c4"],
            "count": 1,
        },
        hypothesis="The agent never learned that src/pty/ paths belong to the pty component.",
        diagnosis="Windows/ConPTY issues get component=core: no rule maps paths to components.",
        diff_path=f"agents/{AGENT_ID}/v{to_version}/CHANGES.diff",
        diff_summary="+3 rules, +1 tool note",
        files_touched=["memory/rules.jsonl"],
    )
    emit(
        "fix_accepted",
        agent_id=AGENT_ID,
        agent_version=to_version,
        lever="memory",
        conn=conn,
        to_version=to_version,
        pass_at_1_before=2 / 3,
        pass_at_1_after=5 / 6,
        pass_pow_k_before=0.5,
        pass_pow_k_after=0.75,
        group_pass_before=0.0,
        group_pass_after=1 / 3,
        holdout_pass_at_1_after=5 / 6,
        holdout_pass_pow_k_after=0.5,
        cost_per_run_before=0.12,
        cost_per_run_after=0.06,
        tool_calls_per_task_before=9,
        tool_calls_per_task_after=4,
    )


def _extraction_response(
    trigger: str = "agent must map free-text input to a fixed label vocabulary",
    lesson: str = "Write one rule per label with the evidence case ids.",
) -> str:
    return json.dumps(
        {
            "lever": "memory",
            "trigger": trigger,
            "lesson": lesson,
            "domain_tags": ["classification"],
        }
    )


def test_scan_records_one_lesson_per_new_fix_accepted(tmp_path, conn, make_complete):
    _seed_fix(conn, to_version=1, issue_id="i1")
    complete, fake = make_complete([_extraction_response()])

    result = scan(conn, playbook_path=tmp_path / "lessons.jsonl", complete=complete)

    assert len(result.lessons) == 1
    assert result.lessons[0]["source_agent_id"] == AGENT_ID
    assert result.lessons[0]["source_issue_id"] == "i1"
    assert fake.call_count == 1
    assert result.last_event_id > 0
    assert (tmp_path / "lessons.jsonl").read_text(encoding="utf-8").strip()


def test_scan_is_idempotent_via_the_since_event_id_watermark(tmp_path, conn, make_complete):
    _seed_fix(conn, to_version=1)
    complete, fake = make_complete([_extraction_response()])
    playbook_path = tmp_path / "lessons.jsonl"

    first = scan(conn, playbook_path=playbook_path, complete=complete)
    assert len(first.lessons) == 1

    second = scan(
        conn, since_event_id=first.last_event_id, playbook_path=playbook_path, complete=complete
    )
    assert second.lessons == []
    assert fake.call_count == 1  # the CHEAP model was never called again


def test_scan_processes_multiple_new_fixes_in_one_call(tmp_path, conn, make_complete):
    _seed_fix(conn, to_version=1)
    _seed_fix(conn, to_version=2)
    complete, fake = make_complete(
        [
            _extraction_response(),
            _extraction_response(
                trigger="agent calls the same tool with identical arguments repeatedly",
                lesson="Cap retries and nudge the agent to change approach.",
            ),
        ]
    )

    result = scan(conn, playbook_path=tmp_path / "lessons.jsonl", complete=complete)

    assert len(result.lessons) == 2
    assert fake.call_count == 2


def test_scan_skips_a_fix_accepted_with_no_matching_fix_proposed(tmp_path, conn, make_complete):
    emit(
        "fix_accepted",
        agent_id=AGENT_ID,
        agent_version=1,
        lever="memory",
        conn=conn,
        to_version=1,
        pass_at_1_before=0.5,
        pass_at_1_after=0.6,
        pass_pow_k_before=0.4,
        pass_pow_k_after=0.5,
        group_pass_before=0.0,
        group_pass_after=0.5,
        holdout_pass_at_1_after=0.5,
        holdout_pass_pow_k_after=0.4,
        cost_per_run_before=0.1,
        cost_per_run_after=0.1,
        tool_calls_per_task_before=5,
        tool_calls_per_task_after=5,
    )
    complete, fake = make_complete([])

    result = scan(conn, playbook_path=tmp_path / "lessons.jsonl", complete=complete)

    assert result.lessons == []
    assert fake.call_count == 0
    assert result.last_event_id > 0  # still advances the watermark past it


def test_scan_and_record_persists_incremental_watermark(tmp_path, conn, make_complete):
    playbook_path = tmp_path / "lessons.jsonl"
    complete, fake = make_complete(
        [
            _extraction_response(),
            _extraction_response(
                trigger="agent repeats a tool call without changing its arguments",
                lesson="Cap identical retries and require the next attempt to change approach.",
            ),
        ]
    )
    _seed_fix(conn, to_version=1)
    first = scan_and_record(conn, playbook_path=playbook_path, complete=complete)
    first_lines = playbook_path.read_text(encoding="utf-8").splitlines()

    repeated = scan_and_record(conn, playbook_path=playbook_path, complete=complete)
    repeated_lines = playbook_path.read_text(encoding="utf-8").splitlines()

    _seed_fix(conn, to_version=2)
    second = scan_and_record(conn, playbook_path=playbook_path, complete=complete)
    second_lines = playbook_path.read_text(encoding="utf-8").splitlines()

    assert len(first.lessons) == 1
    assert repeated.lessons == []
    assert repeated.last_event_id == first.last_event_id
    assert len(second.lessons) == 1
    assert second.last_event_id > first.last_event_id
    assert len(first_lines) == 1
    assert repeated_lines == first_lines
    assert len(second_lines) == 2
    assert second_lines[0] == first_lines[0]
    assert fake.call_count == 2  # one call for each new fix, never the first fix twice
    cursor = conn.execute(
        "SELECT last_event_id FROM playbook_scan_cursors WHERE stream = 'fix_accepted'"
    ).fetchone()
    assert cursor["last_event_id"] == second.last_event_id


def test_scan_and_record_reports_new_duplicate_as_skipped(tmp_path, conn, make_complete):
    playbook_path = tmp_path / "lessons.jsonl"
    complete, fake = make_complete([_extraction_response(), _extraction_response()])

    _seed_fix(conn, to_version=1)
    first = scan_and_record(conn, playbook_path=playbook_path, complete=complete)
    _seed_fix(conn, to_version=2)
    second = scan_and_record(conn, playbook_path=playbook_path, complete=complete)

    assert len(first.lessons) == 1
    assert second.lessons == []
    assert second.skipped_duplicate_event_ids
    assert second.skipped_unusable_event_ids == []
    assert fake.call_count == 2


def test_scan_and_record_does_not_advance_cursor_when_scan_fails(
    tmp_path, conn, make_complete, monkeypatch
):
    complete, _fake = make_complete([])
    initial = scan_and_record(
        conn,
        since_event_id=7,
        playbook_path=tmp_path / "lessons.jsonl",
        complete=complete,
    )
    assert initial.last_event_id == 7

    scan_module = importlib.import_module("backend.playbook.scan")

    def fail_scan(*args, **kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(scan_module, "scan", fail_scan)
    with pytest.raises(RuntimeError, match="scan failed"):
        scan_and_record(conn, since_event_id=11)

    cursor = conn.execute(
        "SELECT last_event_id FROM playbook_scan_cursors WHERE stream = 'fix_accepted'"
    ).fetchone()
    assert cursor["last_event_id"] == 7


def test_scan_and_record_explicit_cursor_overrides_persisted_start(tmp_path, conn, make_complete):
    playbook_path = tmp_path / "lessons.jsonl"
    complete, fake = make_complete([_extraction_response()])
    _seed_fix(conn, to_version=1)
    accepted_id = conn.execute("SELECT id FROM events WHERE kind = 'fix_accepted'").fetchone()["id"]

    skipped = scan_and_record(
        conn,
        since_event_id=accepted_id,
        playbook_path=playbook_path,
        complete=complete,
    )
    replayed = scan_and_record(
        conn,
        since_event_id=0,
        playbook_path=playbook_path,
        complete=complete,
    )
    incremental = scan_and_record(conn, playbook_path=playbook_path, complete=complete)

    assert skipped.lessons == []
    assert len(replayed.lessons) == 1
    assert incremental.lessons == []
    assert fake.call_count == 1
