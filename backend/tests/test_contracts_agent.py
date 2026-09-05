from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.agent import (
    AgentConfig,
    MemoryRule,
    Orchestration,
    PackageError,
    load_package,
    new_entry_id,
    validate_package,
)


def test_toy_package_loads(toy_agent_path: Path):
    assert validate_package(toy_agent_path) == []
    pkg = load_package(toy_agent_path)

    assert pkg.config.name == "toy_agent"
    assert pkg.version == 0
    assert pkg.config.orchestration == Orchestration.single.value
    assert pkg.config.orchestration_reason is None  # optional, absent in this fixture
    assert pkg.config.routing == {"worker": "cheap"}
    assert "toy agent" in pkg.prompt

    assert list(pkg.tools) == ["shout"]
    tool = pkg.tools["shout"]
    assert tool.spec.input_schema["required"] == ["text"]
    assert tool.run({"text": "hello"}) == "HELLO!"


def test_toy_package_memory(toy_agent_path: Path):
    memory = load_package(toy_agent_path).memory
    assert [r.id for r in memory.rules] == ["rule_toy0001", "rule_toy0002"]
    assert [r.id for r in memory.active_rules] == ["rule_toy0001"]  # rule_toy0002 is demoted
    assert memory.tool_notes[0].tool == "shout"
    assert memory.episodes[0].run_id == "r_toy"
    assert "shout" in memory.episodes[0].one_line_reflection


def test_missing_agent_yaml_is_reported(tmp_path: Path, toy_agent_path: Path):
    pkg_dir = tmp_path / "v0"
    shutil.copytree(toy_agent_path, pkg_dir)
    (pkg_dir / "agent.yaml").unlink()

    errors = validate_package(pkg_dir)
    assert any("agent.yaml is missing" in e for e in errors)
    with pytest.raises(PackageError):
        load_package(pkg_dir)


def test_declared_tool_without_a_module_is_reported(tmp_path: Path, toy_agent_path: Path):
    pkg_dir = tmp_path / "v0"
    shutil.copytree(toy_agent_path, pkg_dir)
    (pkg_dir / "tools" / "shout.py").unlink()

    errors = validate_package(pkg_dir)
    assert any("no tools/*.py exposing it" in e for e in errors)


def test_tool_module_without_TOOL_is_reported(tmp_path: Path, toy_agent_path: Path):
    pkg_dir = tmp_path / "v0"
    shutil.copytree(toy_agent_path, pkg_dir)
    (pkg_dir / "tools" / "broken.py").write_text(
        "def run(input):\n    return ''\n", encoding="utf-8"
    )

    errors = validate_package(pkg_dir)
    assert any("must define TOOL" in e for e in errors)


def test_malformed_memory_line_is_reported(tmp_path: Path, toy_agent_path: Path):
    pkg_dir = tmp_path / "v0"
    shutil.copytree(toy_agent_path, pkg_dir)
    rules = pkg_dir / "memory" / "rules.jsonl"
    rules.write_text(rules.read_text(encoding="utf-8") + "{not json}\n", encoding="utf-8")

    errors = validate_package(pkg_dir)
    assert any("rules.jsonl:3" in e for e in errors)


def test_absent_memory_files_load_as_empty(tmp_path: Path, toy_agent_path: Path):
    pkg_dir = tmp_path / "v0"
    shutil.copytree(toy_agent_path, pkg_dir)
    shutil.rmtree(pkg_dir / "memory")

    pkg = load_package(pkg_dir)
    assert pkg.memory.rules == []
    assert pkg.memory.tool_notes == []
    assert pkg.memory.episodes == []


def test_agent_config_rejects_unknown_keys_and_modes():
    base = {
        "name": "a",
        "version": 0,
        "domain": "toy",
        "model_strong": "s",
        "model_cheap": "c",
    }
    AgentConfig.model_validate(base)
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({**base, "orchestration": "generate_critic"})
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({**base, "temperature": 0.2})
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({**base, "routing": {"worker": "medium"}})


def test_memory_rule_defaults():
    rule = MemoryRule(id=new_entry_id("rule"), rule="x", created_version=1, source="reflection")
    assert rule.id.startswith("rule_")
    assert (rule.hits, rule.misses, rule.demoted) == (0, 0, False)
