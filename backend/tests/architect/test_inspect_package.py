from __future__ import annotations

import pytest

from backend.architect import package
from backend.architect.inspect_package import (
    PackageReadError,
    read_package_view,
    read_tool_spec,
    read_tool_specs,
)


def test_read_package_view_matches_a_freshly_written_package(tmp_path):
    package_dir = package.write_package(
        "widget-abc",
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
    view = read_package_view(package_dir)
    assert view["agent_yaml"]["orchestration_reason"] == "one call suffices"
    assert view["prompt"] == "# Prompt\n\nDo the thing."
    assert {tool["name"] for tool in view["tools"]} == {"json_validate", "date_parse"}
    assert all(tool["description"] for tool in view["tools"])
    assert view["memory"] == {"rules": [], "tool_notes": [], "episodes": []}


def test_read_package_view_never_imports_a_tool_file(tmp_path):
    """The core safety property D3 asks for: listing tools must not execute them."""
    package_dir = package.write_package(
        "widget-def",
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
    marker = tmp_path / "side_effect_marker"
    poisoned = package_dir / "tools" / "poisoned.py"
    poisoned.write_text(
        f"import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text('imported')\n\n"
        "TOOL = {'name': 'poisoned', 'description': 'd', 'input_schema': {}}\n\n"
        "def run(input):\n    return '{}'\n",
        encoding="utf-8",
    )

    view = read_package_view(package_dir)

    assert not marker.exists(), "read_package_view must not import tools/*.py"
    assert {tool["name"] for tool in view["tools"]} == {"json_validate", "poisoned"}


def test_read_tool_spec_returns_none_for_a_file_with_no_literal_tool(tmp_path):
    path = tmp_path / "weird.py"
    path.write_text(
        "TOOL = some_function_call()\n\ndef run(input):\n    return ''\n", encoding="utf-8"
    )
    assert read_tool_spec(path) is None


def test_read_tool_spec_returns_none_for_a_syntax_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n", encoding="utf-8")
    assert read_tool_spec(path) is None


def test_read_tool_specs_skips_underscore_prefixed_files(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "real.py").write_text(
        "TOOL = {'name': 'real', 'description': 'd', 'input_schema': {}}\n", encoding="utf-8"
    )
    (tools_dir / "_test_real.py").write_text(
        "TOOL = {'name': 'should_be_skipped', 'description': 'd', 'input_schema': {}}\n",
        encoding="utf-8",
    )
    specs = read_tool_specs(tools_dir)
    assert [spec["name"] for spec in specs] == ["real"]


def test_read_package_view_raises_when_agent_yaml_is_missing(tmp_path):
    (tmp_path / "prompt.md").write_text("p", encoding="utf-8")
    with pytest.raises(PackageReadError):
        read_package_view(tmp_path)


def test_read_package_view_raises_on_a_malformed_memory_line(tmp_path):
    package_dir = package.write_package(
        "widget-ghi",
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
    (package_dir / "memory" / "rules.jsonl").write_text("not json\n", encoding="utf-8")
    with pytest.raises(PackageReadError):
        read_package_view(package_dir)
