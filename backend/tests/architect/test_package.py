from __future__ import annotations

import yaml

from backend.architect import package


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
        domain="github_triage",
        model_strong="strong-model",
        model_cheap="cheap-model",
        tools=["json_validate", "date_parse"],
        orchestration="single",
        orchestration_reason="one call suffices",
        prompt_text="# Prompt\n\nDo the thing.",
        root=tmp_path,
    )
    assert package_dir == tmp_path / "widget-abc123" / "v0"
    assert (package_dir / "prompt.md").read_text(encoding="utf-8") == "# Prompt\n\nDo the thing."
    assert (package_dir / "tools" / "json_validate.py").is_file()
    assert (package_dir / "tools" / "date_parse.py").is_file()
    for filename in package.MEMORY_FILES:
        memory_file = package_dir / "memory" / filename
        assert memory_file.is_file()
        assert memory_file.read_text(encoding="utf-8") == ""

    agent_yaml = yaml.safe_load((package_dir / "agent.yaml").read_text(encoding="utf-8"))
    assert agent_yaml == {
        "name": "widget-abc123",
        "version": 0,
        "domain": "github_triage",
        "model_strong": "strong-model",
        "model_cheap": "cheap-model",
        "tools": ["json_validate", "date_parse"],
        "orchestration": "single",
        "orchestration_reason": "one call suffices",
        "routing": {"plan": "strong", "act": "strong"},
    }

    from contracts.agent import validate_package

    assert validate_package(package_dir) == []


def test_write_package_writes_a_glue_tool_verbatim_and_lists_it_in_agent_yaml(tmp_path):
    glue_tool = {
        "name": "combine_labels",
        "code": (
            "TOOL = {'name': 'combine_labels', 'description': 'd', "
            "'input_schema': {'type': 'object', 'properties': {}}}\n\n"
            "def run(input):\n    return '{}'\n"
        ),
        "test_code": "def test_x():\n    assert True\n",
    }
    package_dir = package.write_package(
        "widget-def456",
        0,
        domain="d",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p",
        glue_tool=glue_tool,
        root=tmp_path,
    )
    assert (package_dir / "tools" / "combine_labels.py").read_text(encoding="utf-8") == glue_tool[
        "code"
    ]
    # Leading underscore: contracts.agent's tools/*.py loader must skip this
    # file, or "test_<name>.py" glob-matches as an undeclared second tool
    # (D2) and POST /agents 500s whenever a glue tool is proposed.
    assert (package_dir / "tools" / "_test_combine_labels.py").read_text(
        encoding="utf-8"
    ) == glue_tool["test_code"]
    assert not (package_dir / "tools" / "test_combine_labels.py").exists()

    agent_yaml = yaml.safe_load((package_dir / "agent.yaml").read_text(encoding="utf-8"))
    assert agent_yaml["tools"] == ["json_validate", "combine_labels"]

    from contracts.agent import validate_package

    assert validate_package(package_dir) == []


def test_write_package_does_not_clobber_existing_memory_files(tmp_path):
    first = package.write_package(
        "widget-ghi789",
        0,
        domain="d",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p",
        root=tmp_path,
    )
    rules_path = first / "memory" / "rules.jsonl"
    rules_path.write_text('{"id": "r1"}\n', encoding="utf-8")

    package.write_package(
        "widget-ghi789",
        0,
        domain="d",
        model_strong="s",
        model_cheap="c",
        tools=["json_validate"],
        orchestration="single",
        orchestration_reason="r",
        prompt_text="p2",
        root=tmp_path,
    )
    assert rules_path.read_text(encoding="utf-8") == '{"id": "r1"}\n'
