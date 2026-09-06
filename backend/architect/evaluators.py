"""List evaluators for ``GET /evaluators``."""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_ROOT = "evaluators"

_TOOL_NAME_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*)`")


def _first_paragraph(readme: str) -> str:
    """The first non-heading paragraph of the README, joined onto one line."""
    for block in readme.strip().split("\n\n"):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        return " ".join(line.strip() for line in block.splitlines())
    return ""


def _allowed_tools(readme: str) -> list[str]:
    """Toolbox tool names mentioned in backticks anywhere in the README."""
    from backend.toolbox import registry as toolbox_registry

    mentioned = {name for name in _TOOL_NAME_RE.findall(readme)}
    return sorted(mentioned & set(toolbox_registry.TOOLBOX))


def _case_counts(cases_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with cases_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            split = json.loads(line).get("split", "unknown")
            counts[split] = counts.get(split, 0) + 1
    return counts


def list_evaluators(root: str | Path = DEFAULT_ROOT) -> list[dict]:
    """Return frontend-ready evaluator metadata, sorted by evaluator id."""
    base = Path(root)
    if not base.is_dir():
        return []

    results: list[dict] = []
    for entry in sorted(base.iterdir()):
        readme_path = entry / "README.md"
        cases_path = entry / "cases.jsonl"
        if not entry.is_dir() or not readme_path.is_file() or not cases_path.is_file():
            continue
        readme = readme_path.read_text(encoding="utf-8")
        results.append(
            {
                "evaluator_id": entry.name,
                "domain": entry.name,
                "description": _first_paragraph(readme),
                "case_counts": _case_counts(cases_path),
                "allowed_tools": _allowed_tools(readme),
            }
        )
    return results
