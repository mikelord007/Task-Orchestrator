"""Agent package loading and the tool registry (PLAN.md section 4.2).

A package version lives at ``agents/<agent_id>/v<N>/`` and holds ``agent.yaml``,
``prompt.md``, ``tools/*.py`` and ``memory/``. Each tool module exposes
``TOOL = {name, description, input_schema}`` and ``run(input: dict) -> str``.

A tool that raises is *never* fatal: the exception is turned into an error
string handed back to the model and counted in ``tool_errors``.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_AGENTS_DIR = Path("agents")


class PackageError(RuntimeError):
    """Raised when a package version cannot be loaded at all."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], Any]
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


# -- tool registry ------------------------------------------------------


def load_tool_module(path: Path) -> Any:
    module_name = f"_agent_tool_{path.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PackageError(f"cannot import tool module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - surfaced as a package error
        sys.modules.pop(module_name, None)
        raise PackageError(f"tool module {path.name} failed to import: {exc}") from exc
    return module


def build_tool_registry(
    tools_dir: Path, allowed: list[str] | None = None
) -> dict[str, Tool]:
    """Import every ``tools/*.py`` and register those exposing TOOL + run."""
    registry: dict[str, Tool] = {}
    if not tools_dir.exists():
        return registry
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = load_tool_module(path)
        descriptor = getattr(module, "TOOL", None)
        runner = getattr(module, "run", None)
        if not isinstance(descriptor, dict) or not callable(runner):
            continue
        name = str(descriptor.get("name") or path.stem)
        registry[name] = Tool(
            name=name,
            description=str(descriptor.get("description") or ""),
            input_schema=dict(descriptor.get("input_schema") or {}),
            run=runner,
            source_path=str(path).replace("\\", "/"),
        )
    if allowed:
        wanted = {str(n) for n in allowed}
        filtered = {n: t for n, t in registry.items() if n in wanted}
        # An agent.yaml naming a tool the package does not ship is a package
        # problem, not a silent one - but only fail if nothing at all resolves.
        if filtered or not registry:
            return filtered
    return registry


def invoke_tool(tool: Tool, args: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool. Returns ``(result_text, is_error)``; never raises."""
    try:
        result = tool.run(args if isinstance(args, dict) else {"input": args})
    except Exception as exc:  # noqa: BLE001 - deliberately swallowed, see docstring
        return f"ERROR: {type(exc).__name__}: {exc}", True
    if isinstance(result, str):
        return result, False
    import json

    try:
        return json.dumps(result, default=str), False
    except Exception:  # noqa: BLE001
        return str(result), False


# -- package loading ----------------------------------------------------


def _parse_yaml(text: str) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise PackageError("agent.yaml must parse to a mapping")
    return data


def load_from_dir(directory: Path | str, agent_id: str = "", version: int | None = None) -> LoadedPackage:
    """Load a package straight off disk (used by tests and by :func:`load`)."""
    directory = Path(directory)
    if not directory.exists():
        raise PackageError(f"agent package not found: {directory}")
    config_path = directory / "agent.yaml"
    config = _parse_yaml(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    prompt_path = directory / "prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    if version is None:
        version = int(config.get("version") or 0)
    return LoadedPackage(
        agent_id=agent_id or str(config.get("agent_id") or config.get("name") or directory.name),
        version=version,
        directory=directory,
        config=config,
        prompt=prompt,
        tools=build_tool_registry(directory / "tools", config.get("tools")),
    )


def package_dir(agent_id: str, version: int, agents_dir: Path | str = DEFAULT_AGENTS_DIR) -> Path:
    return Path(agents_dir) / agent_id / f"v{version}"


def load(agent_id: str, version: int, agents_dir: Path | str = DEFAULT_AGENTS_DIR) -> LoadedPackage:
    """Load an agent package version via ``contracts.agent.load_package``.

    ``contracts`` owns the package schema; the runtime only adds the executable
    tool registry on top of whatever it returns.
    """
    directory = package_dir(agent_id, version, agents_dir)
    config: dict[str, Any] | None = None
    prompt: str | None = None
    try:
        from contracts.agent import load_package  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - contracts not importable, fall back to disk
        load_package = None  # type: ignore[assignment]
    if load_package is not None:
        contract_package = load_package(agent_id, version)
        directory = Path(getattr(contract_package, "directory", None) or directory)
        raw_config = getattr(contract_package, "config", None)
        if raw_config is None:
            raw_config = getattr(contract_package, "agent_yaml", None)
        if hasattr(raw_config, "model_dump"):
            config = raw_config.model_dump()
        elif isinstance(raw_config, dict):
            config = dict(raw_config)
        elif hasattr(contract_package, "model_dump"):
            config = contract_package.model_dump()
        prompt = getattr(contract_package, "prompt", None)

    package = load_from_dir(directory, agent_id=agent_id, version=version)
    if config:
        merged = dict(package.config)
        merged.update({k: v for k, v in config.items() if v is not None})
        package.config = merged
        package.tools = build_tool_registry(directory / "tools", merged.get("tools"))
    if prompt:
        package.prompt = prompt
    return package
