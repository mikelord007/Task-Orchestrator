"""Agent package contracts (PLAN.md section 4.2, amended by 0.2 and 0.4).

An agent version is an immutable directory snapshot::

    agents/<agent_id>/v<N>/
      agent.yaml    # AgentConfig below
      prompt.md     # system prompt
      tools/*.py    # each exposes TOOL = {name, description, input_schema}
                    # and run(input: dict) -> str
      memory/       # rules.jsonl, tool_notes.jsonl, episodes.jsonl  (section E)
      CHANGES.diff  # unified diff from v<N-1>, written by whichever lever changed it

Phase 0 decisions where 4.2 was ambiguous:

* `generate_critic` is dropped (0.4); `Orchestration` is `single | planner_worker`.
* Missing or empty memory jsonl files load as empty lists. A v0 agent starts with
  empty memory on purpose -- that is the first demo beat -- so absence is not an
  error. Malformed lines *are* an error.
* `routing` maps a step name to `strong` or `cheap`. Step names are free-form and
  owned by the orchestration mode (e.g. `planner`, `worker`); the contract only
  fixes the value domain.
* Loading a package imports its `tools/*.py` modules, which executes them. Agent
  packages are locally generated artifacts, not untrusted input. Note for W2:
  `_load_tool_module` pops the module from `sys.modules` after exec, so the
  imported `run` callable is not picklable -- fine for a thread-based eval
  loop, not for a process pool.
* `CHANGES.diff` is not validated by `load_package`/`validate_package` (it is
  provenance, not runtime input); W6 is the only writer.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "Orchestration",
    "ModelTier",
    "AgentConfig",
    "MemoryRule",
    "ToolNote",
    "Episode",
    "AgentMemory",
    "ToolSpec",
    "LoadedTool",
    "AgentPackage",
    "PackageError",
    "load_package",
    "validate_package",
    "new_entry_id",
    "MEMORY_FILES",
]

MEMORY_FILES = ("rules.jsonl", "tool_notes.jsonl", "episodes.jsonl")


class PackageError(ValueError):
    """Raised by `load_package` when a package violates the contract."""

    def __init__(self, path: Path | str, errors: list[str]) -> None:
        self.path = str(path)
        self.errors = errors
        super().__init__(f"invalid agent package at {path}:\n  - " + "\n  - ".join(errors))


class Orchestration(StrEnum):
    single = "single"
    planner_worker = "planner_worker"


class ModelTier(StrEnum):
    strong = "strong"
    cheap = "cheap"


class AgentConfig(BaseModel):
    """`agent.yaml`."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    name: str
    version: int
    domain: str
    model_strong: str
    model_cheap: str
    tools: list[str] = Field(default_factory=list)
    orchestration: Orchestration = Orchestration.single
    orchestration_reason: str | None = None
    routing: dict[str, Literal["strong", "cheap"]] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Memory (section 0.2)
# --------------------------------------------------------------------------


class MemoryRule(BaseModel):
    """`memory/rules.jsonl` -- a hypothesis the gate accepted.

    `hits`/`misses` are written by the runtime from score.py verdicts on cases
    where the runtime injected this rule -- never by the agent (rule 2.8).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    rule: str
    scope_keywords: list[str] = Field(default_factory=list)
    evidence_case_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    hits: int = 0
    misses: int = 0
    created_version: int
    source: Literal["reflection", "issue"]
    demoted: bool = False


class ToolNote(BaseModel):
    """`memory/tool_notes.jsonl` -- learned mechanics of a third-party tool."""

    model_config = ConfigDict(extra="allow")

    id: str
    tool: str
    note: str
    evidence: str
    created_version: int


class Episode(BaseModel):
    """`memory/episodes.jsonl` -- one-line reflection per run (section E)."""

    model_config = ConfigDict(extra="allow")

    version: int
    run_id: str
    one_line_reflection: str


class AgentMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[MemoryRule] = Field(default_factory=list)
    tool_notes: list[ToolNote] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)

    @property
    def active_rules(self) -> list[MemoryRule]:
        """Rules eligible for injection (demoted rules stay on disk, unused)."""
        return [r for r in self.rules if not r.demoted]


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """The `TOOL` dict a `tools/*.py` module must expose."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    input_schema: dict[str, Any]


class LoadedTool(BaseModel):
    """A `ToolSpec` plus the imported `run` callable."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: ToolSpec
    run: Callable[[dict[str, Any]], str]
    module_path: str

    @property
    def name(self) -> str:
        return self.spec.name


class AgentPackage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    config: AgentConfig
    prompt: str
    tools: dict[str, LoadedTool] = Field(default_factory=dict)
    memory: AgentMemory = Field(default_factory=AgentMemory)

    @property
    def version(self) -> int:
        return self.config.version


def new_entry_id(prefix: str) -> str:
    """Stable-format id for a memory entry, e.g. rule_3f2c1a9b4d0e."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _read_jsonl(path: Path, model: type[BaseModel], errors: list[str]) -> list[Any]:
    if not path.exists():
        return []
    out: list[Any] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(model.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"memory/{path.name}:{lineno}: {exc}")
    return out


def _load_tool_module(py: Path, errors: list[str]) -> LoadedTool | None:
    mod_name = f"_agent_tool_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(mod_name, py)
    if spec is None or spec.loader is None:
        errors.append(f"tools/{py.name}: not importable")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report, never crash the loader
        errors.append(f"tools/{py.name}: import failed: {exc}")
        return None
    finally:
        sys.modules.pop(mod_name, None)

    tool = getattr(module, "TOOL", None)
    if not isinstance(tool, dict):
        errors.append(f"tools/{py.name}: must define TOOL = {{name, description, input_schema}}")
        return None
    run = getattr(module, "run", None)
    if not callable(run):
        errors.append(f"tools/{py.name}: must define run(input: dict) -> str")
        return None
    try:
        tool_spec = ToolSpec.model_validate(tool)
    except ValidationError as exc:
        errors.append(f"tools/{py.name}: bad TOOL dict: {exc}")
        return None
    return LoadedTool(spec=tool_spec, run=run, module_path=str(py))


def _load(path: Path) -> tuple[AgentPackage | None, list[str]]:
    errors: list[str] = []
    if not path.is_dir():
        return None, [f"{path} is not a directory"]

    config: AgentConfig | None = None
    yaml_path = path / "agent.yaml"
    if not yaml_path.exists():
        errors.append("agent.yaml is missing")
    else:
        try:
            config = AgentConfig.model_validate(
                yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            )
        except (yaml.YAMLError, ValidationError) as exc:
            errors.append(f"agent.yaml: {exc}")

    prompt_path = path / "prompt.md"
    prompt = ""
    if not prompt_path.exists():
        errors.append("prompt.md is missing")
    else:
        prompt = prompt_path.read_text(encoding="utf-8")
        if not prompt.strip():
            errors.append("prompt.md is empty")

    tools: dict[str, LoadedTool] = {}
    tools_dir = path / "tools"
    if tools_dir.is_dir():
        for py in sorted(tools_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            loaded = _load_tool_module(py, errors)
            if loaded is not None:
                if loaded.name in tools:
                    errors.append(f"tools/{py.name}: duplicate tool name {loaded.name!r}")
                tools[loaded.name] = loaded

    if config is not None:
        for declared in config.tools:
            if declared not in tools:
                errors.append(
                    f"agent.yaml declares tool {declared!r} with no tools/*.py exposing it"
                )

    mem_dir = path / "memory"
    memory = AgentMemory(
        rules=_read_jsonl(mem_dir / "rules.jsonl", MemoryRule, errors),
        tool_notes=_read_jsonl(mem_dir / "tool_notes.jsonl", ToolNote, errors),
        episodes=_read_jsonl(mem_dir / "episodes.jsonl", Episode, errors),
    )

    if errors or config is None:
        return None, errors
    return (
        AgentPackage(
            path=str(path),
            config=config,
            prompt=prompt,
            tools=tools,
            memory=memory,
        ),
        errors,
    )


def validate_package(path: Path | str) -> list[str]:
    """Return contract violations for the package at `path` (empty list = valid)."""
    _, errors = _load(Path(path))
    return errors


def load_package(path: Path | str) -> AgentPackage:
    """Load and validate an agent package version directory.

    Raises `PackageError` listing every violation found.
    """
    package, errors = _load(Path(path))
    if package is None:
        raise PackageError(path, errors or ["unknown error"])
    return package
