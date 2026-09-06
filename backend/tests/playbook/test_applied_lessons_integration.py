"""End-to-end check that a lesson *this module* records is the same lesson
W3's architect applies (brief item: "Verify W3's `applied_lessons` is
populated when `use_playbook=true` and lessons exist; add a test.").

``backend.architect.playbook_reader`` already reads ``playbook/lessons.jsonl``
and ``backend.architect.generate`` already records the applied ids into
``agent_created.applied_lessons`` -- this test proves the two workstreams
agree on the file, not just on paper.
"""

from __future__ import annotations

import json

import pytest

from backend.architect.generate import generate
from backend.ledger.emit import read as read_events
from backend.playbook.record import record_lesson


@pytest.fixture
def evaluator_dir(tmp_path):
    base = tmp_path / "evaluators" / "github_triage"
    base.mkdir(parents=True)
    (base / "README.md").write_text(
        "# github_triage\n\nGiven an issue, decide its labels and component.\n",
        encoding="utf-8",
    )
    rows = [
        {
            "id": "c1",
            "split": "train",
            "input": {"issue_number": 1},
            "expected": {"labels": ["bug"], "component": "core"},
            "tags": [],
        },
    ]
    (base / "cases.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return tmp_path / "evaluators"


def test_a_recorded_lesson_is_applied_by_the_architect(
    evaluator_dir, tmp_path, make_complete, conn
):
    playbook_path = tmp_path / "playbook" / "lessons.jsonl"
    recorded = record_lesson(
        lever="memory",
        trigger="agent must map free-text input to a fixed label vocabulary",
        lesson="Write one rule per label describing the signal that selects it.",
        domain_tags=["github_triage", "classification"],
        source_agent_id="a_source",
        playbook_path=playbook_path,
        conn=conn,
    )
    assert recorded is not None

    responses = [
        json.dumps({"mode": "single", "reason": "One call is enough for this task."}),
        "Answer with a JSON object with keys: labels, component.",
        json.dumps({"tools": ["json_validate"], "glue_tool": None}),
        json.dumps(
            {
                "prompt": "Revised prompt applying the lesson. Answer with a JSON object "
                "with keys: labels, component.",
                "applied_lesson_ids": [recorded["id"]],
            }
        ),
    ]
    complete, fake = make_complete(responses)

    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate"],
        evaluator_id="github_triage",
        use_playbook=True,
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
        playbook_path=playbook_path,
        conn=conn,
    )

    assert result.applied_lessons == [recorded["id"]]
    assert fake.call_count == 4

    events = read_events(kind="agent_created", agent_id=result.agent_id, conn=conn)
    assert events[0]["payload"]["applied_lessons"] == [recorded["id"]]


def test_use_playbook_false_never_applies_a_recorded_lesson(
    evaluator_dir, tmp_path, make_complete, conn
):
    playbook_path = tmp_path / "playbook" / "lessons.jsonl"
    record_lesson(
        lever="memory",
        trigger="agent must map free-text input to a fixed label vocabulary",
        lesson="Write one rule per label.",
        domain_tags=["github_triage"],
        source_agent_id="a_source",
        playbook_path=playbook_path,
        conn=conn,
    )

    responses = [
        json.dumps({"mode": "single", "reason": "One call is enough for this task."}),
        "Answer with a JSON object with keys: labels, component.",
        json.dumps({"tools": ["json_validate"], "glue_tool": None}),
    ]
    complete, fake = make_complete(responses)

    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate"],
        evaluator_id="github_triage",
        use_playbook=False,
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
        playbook_path=playbook_path,
        conn=conn,
    )

    assert result.applied_lessons == []
    assert fake.call_count == 3  # never read the playbook step
