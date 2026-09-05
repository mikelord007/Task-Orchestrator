from __future__ import annotations

import json

import yaml
from architect.generate import generate
from fakes import FakeComplete


def _responses(*, use_playbook: bool = False) -> list[str]:
    responses = [
        json.dumps({"mode": "single", "reason": "One call is enough for this task."}),
        "Answer with a JSON object with keys: labels, component.",
        json.dumps({"tools": ["json_validate", "date_parse"], "glue_tool": None}),
    ]
    if use_playbook:
        responses.append(
            json.dumps(
                {"prompt": "Revised prompt with lesson.", "applied_lesson_ids": ["l1"]}
            )
        )
    return responses


def test_generate_writes_a_full_package_and_returns_a_result(evaluator_dir, tmp_path):
    complete = FakeComplete(_responses())
    result = generate(
        goal="triage github issues",
        domain="github_triage",
        tools=["json_validate", "date_parse", "not_a_real_tool"],
        evaluator_id="widget_triage",
        complete=complete,
        model="strong-model",
        agents_root=tmp_path / "agents",
        evaluators_root=evaluator_dir,
    )

    assert result.version == 0
    assert result.orchestration == {
        "mode": "single",
        "reason": "One call is enough for this task.",
    }
    assert result.tools == ["json_validate", "date_parse"]
    assert result.glue_tool is None
    assert result.applied_lessons == []
    assert result.finalized is False  # contracts/db/ledger aren't on this branch yet
    assert len(result.llm_calls) == 3
    assert all(call["cost_usd"] == 0.001 for call in result.llm_calls)

    assert result.package_dir.is_dir()
    assert (result.package_dir / "prompt.md").is_file()
    assert (result.package_dir / "tools" / "json_validate.py").is_file()
    for filename in ("rules.jsonl", "tool_notes.jsonl", "episodes.jsonl"):
        assert (result.package_dir / "memory" / filename).is_file()

    agent_yaml = yaml.safe_load(
        (result.package_dir / "agent.yaml").read_text(encoding="utf-8")
    )
    assert agent_yaml["model_strong"] == "strong-model"
    assert agent_yaml["evaluator_id"] == "widget_triage"


def test_generate_uses_the_playbook_when_asked(evaluator_dir, tmp_path):
    lessons_path = tmp_path / "lessons.jsonl"
    lessons_path.write_text(
        json.dumps(
            {
                "id": "l1",
                "lever": "prompt",
                "lesson": "x",
                "domain_tags": ["github_triage"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    complete = FakeComplete(_responses(use_playbook=True))
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
    )
    assert result.applied_lessons == ["l1"]
    assert result.prompt_text == "Revised prompt with lesson."
    assert len(result.llm_calls) == 4
    assert (result.package_dir / "prompt.md").read_text(
        encoding="utf-8"
    ) == "Revised prompt with lesson."


def test_generate_ignores_the_playbook_when_not_asked(evaluator_dir, tmp_path):
    complete = FakeComplete(_responses(use_playbook=False))
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
    )
    assert result.applied_lessons == []
    assert len(result.llm_calls) == 3
