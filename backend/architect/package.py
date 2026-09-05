"""Assemble and write an agent package directory (``agents/<id>/v<n>/``).

See ``contracts/agent_package.md``.
"""

from __future__ import annotations

import random
import re
import string
from pathlib import Path

import yaml

from backend.toolbox import registry as toolbox_registry

DEFAULT_AGENTS_ROOT = "agents"
MEMORY_FILES = ("rules.jsonl", "tool_notes.jsonl", "episodes.jsonl")


def slugify(domain: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", domain.strip().lower()).strip("-")
    return slug or "agent"


def make_agent_id(domain: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{slugify(domain)}-{suffix}"


def _write_glue_tool(tools_dir: Path, glue_tool: dict) -> None:
    name = glue_tool["name"]
    (tools_dir / f"{name}.py").write_text(glue_tool["code"], encoding="utf-8")
    # Leading underscore: contracts.agent's tools/*.py loader skips these, so
    # the test file is never mistaken for a second tool module (a bare
    # "test_<name>.py" glob-matches *.py and load_package rejects it as an
    # undeclared duplicate-shaped tool).
    (tools_dir / f"_test_{name}.py").write_text(glue_tool["test_code"], encoding="utf-8")


def write_package(
    agent_id: str,
    version: int,
    *,
    domain: str,
    model_strong: str,
    model_cheap: str,
    tools: list[str],
    orchestration: str,
    orchestration_reason: str,
    prompt_text: str,
    glue_tool: dict | None = None,
    root: str | Path = DEFAULT_AGENTS_ROOT,
) -> Path:
    """Write ``<root>/<agent_id>/v<version>/`` and return its path.

    Layout matches ``contracts/agent_package.md`` exactly: ``agent.yaml``
    (``name, version, domain, model_strong, model_cheap, tools, orchestration,
    orchestration_reason, routing`` -- ``AgentConfig`` is ``extra="forbid"``,
    so nothing else goes in it), ``prompt.md``, ``tools/*.py`` (re-exported
    from the toolbox via ``toolbox.registry.write_agent_tools``, plus the glue
    tool's own files written verbatim if one was proposed), and three empty
    ``memory/*.jsonl`` files. Package *validation* against ``contracts.agent``
    happens one layer up, in ``generate._finalize``.

    ``goal`` and ``evaluator_id`` belong to the ``agents`` DB row, not this
    file; ``applied_lessons`` belongs to the ``agent_created`` ledger event --
    none of the three are part of ``agent.yaml``, so this function does not
    take them.
    """
    package_dir = Path(root) / agent_id / f"v{version}"
    tools_dir = package_dir / "tools"
    memory_dir = package_dir / "memory"
    tools_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)

    (package_dir / "prompt.md").write_text(prompt_text, encoding="utf-8")

    toolbox_registry.write_agent_tools(tools, tools_dir)
    all_tool_names = list(tools)
    if glue_tool is not None:
        _write_glue_tool(tools_dir, glue_tool)
        all_tool_names.append(glue_tool["name"])

    for filename in MEMORY_FILES:
        memory_path = memory_dir / filename
        if not memory_path.exists():
            memory_path.write_text("", encoding="utf-8")

    agent_yaml = {
        "name": agent_id,
        "version": version,
        "domain": domain,
        "model_strong": model_strong,
        "model_cheap": model_cheap,
        "tools": all_tool_names,
        "orchestration": orchestration,
        "orchestration_reason": orchestration_reason,
        "routing": {"plan": "strong", "act": "strong"},
    }
    (package_dir / "agent.yaml").write_text(
        yaml.safe_dump(agent_yaml, sort_keys=False), encoding="utf-8"
    )
    return package_dir
