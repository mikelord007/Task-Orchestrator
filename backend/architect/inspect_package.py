"""Read an agent package's agent.yaml/prompt/tools/memory without executing anything.

``contracts.agent.load_package`` imports (executes) every ``tools/*.py`` module
to check it exposes a callable ``run``. That is the right thing to do once,
when validating a freshly generated package (``generate._finalize``), but it
is the wrong thing to do on every ``GET /agents/{id}`` -- especially once a
glue tool (LLM-authored code) can exist in a package (``ARCHITECT_ALLOW_GLUE_TOOLS``).
This module reads the same files structurally instead: ``TOOL`` is parsed with
``ast.literal_eval`` off the ``TOOL = {...}`` assignment (which
``toolbox.registry.write_agent_tool`` always writes as a literal, precisely so
this works), never imported.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from contracts.agent import AgentConfig, Episode, MemoryRule, ToolNote

__all__ = ["PackageReadError", "read_tool_spec", "read_tool_specs", "read_package_view"]


class PackageReadError(ValueError):
    """Raised when agent.yaml or prompt.md is missing or invalid."""

    def __init__(self, path: Path | str, errors: list[str]) -> None:
        self.path = str(path)
        self.errors = errors
        super().__init__(f"cannot read agent package at {path}:\n  - " + "\n  - ".join(errors))


def read_tool_spec(path: Path) -> dict | None:
    """The ``TOOL`` dict from one ``tools/*.py`` file, parsed without importing it.

    Returns ``None`` if the file has no top-level ``TOOL = <literal>``
    assignment, or the literal cannot be evaluated (e.g. it references a name
    rather than being self-contained, as a re-export written before
    `toolbox.registry`'s literal-dict change would have). Never raises on
    malformed or even adversarial source: a syntax error is just a miss.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TOOL" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, dict) else None
    return None


def read_tool_specs(tools_dir: Path) -> list[dict]:
    """``[{name, description}, ...]`` for every tool in ``tools_dir``, sorted by name."""
    if not tools_dir.is_dir():
        return []
    specs: list[dict] = []
    for py in sorted(tools_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        spec = read_tool_spec(py)
        if spec and spec.get("name"):
            specs.append({"name": spec["name"], "description": spec.get("description", "")})
    return sorted(specs, key=lambda entry: entry["name"])


def _read_memory(path: Path, model, errors: list[str]) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            entries.append(model.model_validate(json.loads(line)).model_dump())
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"memory/{path.name}:{lineno}: {exc}")
    return entries


def read_package_view(package_dir: Path) -> dict:
    """``{agent_yaml, prompt, tools, memory}`` for one package version, without importing it."""
    errors: list[str] = []

    yaml_path = package_dir / "agent.yaml"
    config: AgentConfig | None = None
    if not yaml_path.is_file():
        errors.append("agent.yaml is missing")
    else:
        try:
            config = AgentConfig.model_validate(
                yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            )
        except (yaml.YAMLError, ValidationError) as exc:
            errors.append(f"agent.yaml: {exc}")

    prompt_path = package_dir / "prompt.md"
    if not prompt_path.is_file():
        errors.append("prompt.md is missing")

    if errors:
        raise PackageReadError(package_dir, errors)

    memory_dir = package_dir / "memory"
    memory = {
        "rules": _read_memory(memory_dir / "rules.jsonl", MemoryRule, errors),
        "tool_notes": _read_memory(memory_dir / "tool_notes.jsonl", ToolNote, errors),
        "episodes": _read_memory(memory_dir / "episodes.jsonl", Episode, errors),
    }
    if errors:
        raise PackageReadError(package_dir, errors)

    return {
        "agent_yaml": config.model_dump(),
        "prompt": prompt_path.read_text(encoding="utf-8"),
        "tools": read_tool_specs(package_dir / "tools"),
        "memory": memory,
    }
