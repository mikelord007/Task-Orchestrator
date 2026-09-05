"""The registry: what is in the toolbox and how it is materialised into an agent package."""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from backend.toolbox import registry

EXPECTED_TOOLS = {
    "html_to_text",
    "regex_extract",
    "date_parse",
    "json_validate",
    "number_parse",
    "github_get_issue_context",
    "github_search_similar_issues",
    "github_get_label_taxonomy",
    "github_find_component_owners",
}


def test_the_toolbox_contains_exactly_the_documented_tools():
    assert set(registry.TOOLBOX) == EXPECTED_TOOLS


def test_github_and_offline_tools_partition_the_toolbox():
    # Four consolidated, task-shaped tools per PLAN_ADDENDUM.md section F --
    # not one wrapper per REST endpoint.
    assert set(registry.GITHUB_TOOLS) | set(registry.OFFLINE_TOOLS) == EXPECTED_TOOLS
    assert not set(registry.GITHUB_TOOLS) & set(registry.OFFLINE_TOOLS)
    assert all(name.startswith("github_") for name in registry.GITHUB_TOOLS)
    assert len(registry.GITHUB_TOOLS) == 4


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_every_registered_module_satisfies_the_tool_contract(name):
    module = registry.TOOLBOX[name]
    assert module.TOOL["name"] == name, "the registry key must match TOOL['name']"
    assert set(module.TOOL) == {"name", "description", "input_schema"}
    assert callable(module.run)

    schema = module.TOOL["input_schema"]
    assert schema["type"] == "object"
    assert isinstance(schema.get("properties"), dict)
    assert isinstance(schema.get("required", []), list)
    assert set(schema.get("required", [])) <= set(schema["properties"])


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_every_description_says_what_it_returns_when_to_use_it_and_what_it_does_not_do(
    name,
):
    description = registry.TOOLBOX[name].TOOL["description"]
    assert len(description) > 300, "descriptions are the agent's only documentation"
    lowered = description.lower()
    assert "returns" in lowered, "say what comes back"
    assert "does not" in lowered, (
        "say what the tool will not do, so the agent stops asking"
    )
    # A one-line summary, then at least: what it returns, when to reach for it,
    # what it will not do, and argument semantics.
    assert description.count("\n\n") >= 3, "description is missing a section"


def test_specs_returns_llm_ready_definitions_for_a_selection():
    selected = registry.specs(["github_get_issue_context", "json_validate"])
    assert [tool["name"] for tool in selected] == [
        "github_get_issue_context",
        "json_validate",
    ]
    assert registry.specs() == [registry.spec(name) for name in sorted(EXPECTED_TOOLS)]
    # Must survive a JSON round trip: this is what goes on the wire to the model.
    assert json.loads(json.dumps(selected)) == selected


def test_unknown_names_are_reported_not_raised_by_run():
    result = registry.run("no_such_tool", {})
    assert result.startswith("ERROR:")
    assert "no_such_tool" in result
    assert "json_validate" in result, "the error should list what is available"


def test_get_raises_a_listing_error_and_unknown_reports_the_bad_names():
    with pytest.raises(registry.UnknownToolError):
        registry.get("no_such_tool")
    assert registry.unknown(["json_validate", "nope", "also_nope"]) == [
        "nope",
        "also_nope",
    ]
    assert registry.unknown(list(EXPECTED_TOOLS)) == []


def test_run_dispatches_to_the_right_module():
    result = json.loads(registry.run("json_validate", {"text": '{"a": 1}'}))
    assert result["valid"] is True


def _import_from_path(name: str, path):
    spec = importlib.util.spec_from_file_location(f"_generated_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_write_agent_tool_emits_an_importable_re_export(tmp_path):
    path = registry.write_agent_tool("json_validate", tmp_path / "tools")
    assert path == tmp_path / "tools" / "json_validate.py"

    source = path.read_text(encoding="utf-8")
    assert "import TOOL, run" in source
    assert registry.TOOLBOX["json_validate"].__name__ in source
    assert "Do not edit by hand" in source

    generated = _import_from_path("json_validate", path)
    assert generated.TOOL is registry.TOOLBOX["json_validate"].TOOL
    assert generated.run is registry.TOOLBOX["json_validate"].run
    assert json.loads(generated.run({"text": "[]"}))["top_level_type"] == "array"


def test_write_agent_tool_works_for_a_github_tool_and_creates_the_directory(tmp_path):
    dest = tmp_path / "agents" / "gh" / "v0" / "tools"
    assert not dest.exists()
    path = registry.write_agent_tool("github_get_issue_context", dest)
    assert path.is_file()
    generated = _import_from_path("github_get_issue_context", path)
    assert generated.TOOL["name"] == "github_get_issue_context"


def test_write_agent_tools_materialises_a_whole_package_and_is_idempotent(tmp_path):
    names = ["github_get_label_taxonomy", "github_get_issue_context", "json_validate"]
    first = registry.write_agent_tools(names, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        f"{n}.py" for n in names
    )
    before = {p: p.read_text(encoding="utf-8") for p in first}
    registry.write_agent_tools(names, tmp_path)
    assert {p: p.read_text(encoding="utf-8") for p in first} == before


def test_write_agent_tool_rejects_an_unknown_name(tmp_path):
    with pytest.raises(registry.UnknownToolError):
        registry.write_agent_tool("not_a_tool", tmp_path)
    assert list(tmp_path.iterdir()) == []
