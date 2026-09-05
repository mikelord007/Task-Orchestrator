"""Agent package loading (PLAN.md section 4.2).

A package version lives at ``agents/<agent_id>/v<N>/`` and holds ``agent.yaml``,
``prompt.md``, ``tools/*.py`` and ``memory/``. ``contracts.agent.load_package``
owns parsing and validation (including importing ``tools/*.py`` and building
the callable tool registry); this module only adapts its result into the
shape the loop/eval harness use and adds :func:`invoke_tool`, which turns a
tool exception into an error string instead of ever crashing a case.

Memory (``rules.jsonl``/``tool_notes.jsonl``) is read separately, straight off
disk, by ``backend/runtime/memory.py`` - the runtime injects and demotes rules
by id, which does not need the contract's pydantic ``MemoryRule`` objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contracts.agent import AgentPackage, load_package

DEFAULT_AGENTS_DIR = Path("agents")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Any
    source_path: str | None = None

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class LoadedPackage:
    agent_id: str
    version: int
    directory: Path
    config: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    tools: dict[str, Tool] = field(default_factory=dict)

    @property
    def orchestration(self) -> str:
        return str(self.config.get("orchestration") or "single")

    @property
    def routing(self) -> dict[str, str]:
        routing = self.config.get("routing") or {}
        return {str(k): str(v) for k, v in routing.items()} if isinstance(routing, dict) else {}

    def tool_specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self.tools.values()]

    def model_for(self, step: str, *, strong: str, cheap: str) -> str:
        """Model for one loop step, from ``agent.yaml.routing`` (default strong).

        W10 extends routing later; the mapping lives here so it stays one place.
        """
        tier = self.routing.get(step, "strong").lower()
        configured = self.config.get(f"model_{tier}")
        if configured:
            return str(configured)
        return cheap if tier == "cheap" else strong


def _adapt(contract_package: AgentPackage, agent_id: str, directory: Path) -> LoadedPackage:
    tools = {
        name: Tool(
            name=loaded.name,
            description=loaded.spec.description,
            input_schema=loaded.spec.input_schema,
            run=loaded.run,
            source_path=loaded.module_path,
        )
        for name, loaded in contract_package.tools.items()
    }
    return LoadedPackage(
        agent_id=agent_id,
        version=contract_package.version,
        directory=directory,
        config=contract_package.config.model_dump(mode="json"),
        prompt=contract_package.prompt,
        tools=tools,
    )


def package_dir(agent_id: str, version: int, agents_dir: Path | str = DEFAULT_AGENTS_DIR) -> Path:
    return Path(agents_dir) / agent_id / f"v{version}"


def load(agent_id: str, version: int, agents_dir: Path | str = DEFAULT_AGENTS_DIR) -> LoadedPackage:
    """Load and validate an agent package version. Raises ``contracts.agent.PackageError``
    listing every contract violation if the package on disk is invalid."""
    directory = package_dir(agent_id, version, agents_dir)
    return _adapt(load_package(directory), agent_id, directory)


def load_from_dir(
    directory: Path | str, agent_id: str = "", version: int | None = None
) -> LoadedPackage:
    """Load a package straight off a directory (used by tests, and by
    :func:`load` once the directory is resolved)."""
    directory = Path(directory)
    contract_package = load_package(directory)
    resolved_id = agent_id or contract_package.config.name
    return _adapt(contract_package, resolved_id, directory)


def invoke_tool(tool: Tool, args: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool. Returns ``(result_text, is_error)``; never raises."""
    try:
        result = tool.run(args if isinstance(args, dict) else {"input": args})
    except Exception as exc:  # noqa: BLE001 - deliberately swallowed, see module docstring
        return f"ERROR: {type(exc).__name__}: {exc}", True
    if isinstance(result, str):
        return result, False
    try:
        return json.dumps(result, default=str), False
    except Exception:  # noqa: BLE001
        return str(result), False
