from __future__ import annotations

import yaml
from architect import package


def test_slugify_normalizes_and_strips():
    assert package.slugify("GitHub Triage!!") == "github-triage"
    assert package.slugify("   ") == "agent"


def test_make_agent_id_is_domain_prefixed_and_unique():
    first = package.make_agent_id("github_triage")
    second = package.make_agent_id("github_triage")
    assert first.startswith("github-triage-")
    assert first != second


def test_write_package_creates_the_full_layout(tmp_path):
    package_dir = package.write_package(
        "widget-abc123",
        0,
        goal="triage issues",
        domain="github_triage",
        evaluator_id="widget_triage",
        model_strong="strong-model",
        model_cheap="cheap-model",
        tools=["json_validate", "date_parse"],
        orchestration="single",
        orchestration_reason="one call suffices",
        prompt_text="# Prompt\n\nDo the thing.",
        applied_lessons=["l1"],
        root=tmp_path,
    )
    assert package_dir == tmp_path / "widget-abc123" / "v0"
    assert (package_dir / "prompt.md").read_text(
        encoding="utf-8"
    ) == "# Prompt\n\nDo the thing."
    assert (package_dir / "tools" / "json_validate.py").is_file()
    assert (package_dir / "tools" / "date_parse.py").is_file()
    for filename in package.MEMORY_FILES:
        memory_file = package_dir / "memory" / filename
        assert memory_file.is_file()
        assert memory_file.read_text(encoding="utf-8") == ""

    agent_yaml = yaml.safe_load(
        (package_dir / "agent.yaml").read_text(encoding="utf-8")
    )
    assert agent_yaml["name"] == "widget-abc123"
    assert agent_yaml["version"] == 0
    assert agent_yaml["tools"] == ["json_validate", "date_parse"]
    assert agent_yaml["orchestration"] == "single"
    assert agent_yaml["routing"] == {"plan": "strong", "act": "strong"}
    assert agent_yaml["applied_lessons"] == ["l1"]


def test_write_package_writes_a_glue_tool_verbatim_and_lists_it_in_agent_yaml(tmp_path):
    glue_tool = {
        "name": "combine_labels",
        "code": "TOOL = {}\n\n\ndef run(input):\n    return '{}'\n",
        "test_code": "def test_x():\n    assert True\n",
    }
    package_dir = package.write_package(
        "widget-def456",
        0,
        goal="g",
        domain="d",
        evaluator_id="e",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p",
        applied_lessons=[],
        glue_tool=glue_tool,
        root=tmp_path,
    )
    assert (package_dir / "tools" / "combine_labels.py").read_text(
        encoding="utf-8"
    ) == glue_tool["code"]
    assert (package_dir / "tools" / "test_combine_labels.py").read_text(
        encoding="utf-8"
    ) == glue_tool["test_code"]
    agent_yaml = yaml.safe_load(
        (package_dir / "agent.yaml").read_text(encoding="utf-8")
    )
    assert agent_yaml["tools"] == ["json_validate", "combine_labels"]


def test_write_package_does_not_clobber_existing_memory_files(tmp_path):
    first = package.write_package(
        "widget-ghi789",
        0,
        goal="g",
        domain="d",
        evaluator_id="e",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p",
        applied_lessons=[],
        root=tmp_path,
    )
    rules_path = first / "memory" / "rules.jsonl"
    rules_path.write_text('{"id": "r1"}\n', encoding="utf-8")

    package.write_package(
        "widget-ghi789",
        0,
        goal="g",
        domain="d",
        evaluator_id="e",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p2",
        applied_lessons=[],
        root=tmp_path,
    )
    assert rules_path.read_text(encoding="utf-8") == '{"id": "r1"}\n'
