from __future__ import annotations

import json

import yaml

from backend.architect.generate import generate
from backend.ledger.emit import read as read_events
from contracts.agent import validate_package


def _responses(*, use_playbook: bool = False) -> list[str]:
    responses = [
        json.dumps({"mode": "single", "reason": "One call is enough for this task."}),
        "Answer with a JSON object with keys: labels, component.",
        json.dumps({"tools": ["json_validate", "date_parse"], "glue_tool": None}),
    ]
    if use_playbook:
        responses.append(
            json.dumps({"prompt": "Revised prompt with lesson.", "applied_lesson_ids": ["l1"]})
        )
    return responses


def test_generate_writes_a_valid_package_and_finalizes(
    evaluator_dir, tmp_path, make_complete, conn
):
    complete, fake = make_complete(_responses())
    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate", "date_parse", "not_a_real_tool"],
        evaluator_id="widget_triage",
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
        conn=conn,
    )

    assert result.version == 0
    assert result.orchestration == {
        "mode": "single",
        "reason": "One call is enough for this task.",
    }
    assert result.tools == ["json_validate", "date_parse"]
    assert result.glue_tool is None
    assert result.applied_lessons == []
    assert result.finalized is True
    assert len(result.llm_calls) == 3
    assert fake.call_count == 3

    # The core acceptance criterion: the written package validates.
    assert validate_package(result.package_dir) == []

    agent_yaml = yaml.safe_load((result.package_dir / "agent.yaml").read_text(encoding="utf-8"))
    assert agent_yaml["model_strong"] == "strong-model"
    assert agent_yaml["orchestration_reason"] == "One call is enough for this task."

    row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (result.agent_id,)).fetchone()
    assert row is not None
    assert row["goal"] == "triage github issues"
    assert row["evaluator_id"] == "widget_triage"
    assert row["current_version"] == 0

    events = read_events(kind="agent_created", agent_id=result.agent_id, conn=conn)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["goal"] == "triage github issues"
    assert payload["tools"] == ["json_validate", "date_parse"]
    assert payload["orchestration"] == "single"
    assert payload["applied_lessons"] == []


def test_generate_emits_applied_lessons_when_the_playbook_is_used(
    evaluator_dir, tmp_path, make_complete, conn
):
    lessons_path = tmp_path / "lessons.jsonl"
    lessons_path.write_text(
        json.dumps({"id": "l1", "lever": "prompt", "lesson": "x", "domain_tags": ["github_triage"]})
        + "\n",
        encoding="utf-8",
    )
    complete, fake = make_complete(_responses(use_playbook=True))
    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate"],
        evaluator_id="widget_triage",
        use_playbook=True,
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
        playbook_path=lessons_path,
        conn=conn,
    )
    assert result.applied_lessons == ["l1"]
    assert result.prompt_text == "Revised prompt with lesson."
    assert len(result.llm_calls) == 4
    assert fake.call_count == 4
    assert result.finalized is True
    assert validate_package(result.package_dir) == []
    assert (result.package_dir / "prompt.md").read_text(
        encoding="utf-8"
    ) == "Revised prompt with lesson."

    events = read_events(kind="agent_created", agent_id=result.agent_id, conn=conn)
    assert events[0]["payload"]["applied_lessons"] == ["l1"]


def test_generate_ignores_the_playbook_when_not_asked(evaluator_dir, tmp_path, make_complete, conn):
    complete, fake = make_complete(_responses(use_playbook=False))
    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate"],
        evaluator_id="widget_triage",
        use_playbook=False,
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
        conn=conn,
    )
    assert result.applied_lessons == []
    assert len(result.llm_calls) == 3
    assert fake.call_count == 3
