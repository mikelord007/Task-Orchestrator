"""Structured agent memory (PLAN.md section 0.2).

``agents/<id>/v<N>/memory/`` holds ``rules.jsonl``, ``tool_notes.jsonl`` and
``episodes.jsonl``. Before every case the runtime injects *all* tool notes plus
the top-K rules whose ``scope_keywords`` overlap the case input, as a clearly
delimited block appended to the system prompt.

Two rule-2.8 invariants live here:

* ``rules_injected`` is decided and recorded by the runtime, never by the agent.
* ``hits``/``misses`` come from ``score.py`` verdicts on the cases where the
  runtime injected the rule - never from the agent's own assessment.

The ledger is the source of truth for demotion; the ``demoted`` flag written
back into ``rules.jsonl`` is only a display cache.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

MEMORY_BLOCK_START = "=== AGENT MEMORY (injected by the runtime from observed results) ==="
MEMORY_BLOCK_END = "=== END AGENT MEMORY ==="

RULES_FILE = "rules.jsonl"
TOOL_NOTES_FILE = "tool_notes.jsonl"
EPISODES_FILE = "episodes.jsonl"

# A rule with no scope_keywords applies everywhere, but ranks below any rule
# that actually matched a keyword.
GLOBAL_RULE_SCORE = 0.5

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def tokenize(text: Any) -> set[str]:
    """Lowercase, split on non-alphanumerics. No embeddings, by design."""
    if not text:
        return set()
    return {tok for tok in _TOKEN_SPLIT.split(str(text).lower()) if tok}


def case_text(case_input: Any) -> str:
    """Flatten a case input (dict/list/scalar) into one searchable string."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, sub in value.items():
                parts.append(str(key))
                walk(sub)
        elif isinstance(value, (list, tuple, set)):
            for sub in value:
                walk(sub)
        elif value is not None:
            parts.append(str(value))

    walk(case_input)
    return " ".join(parts)


# -- disk ---------------------------------------------------------------


@dataclass
class Memory:
    rules: list[dict[str, Any]] = field(default_factory=list)
    tool_notes: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)


def load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_jsonl(path: Path | str, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, default=str) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def memory_dir(package_dir: Path | str) -> Path:
    return Path(package_dir) / "memory"


def load_memory(package_dir: Path | str) -> Memory:
    root = memory_dir(package_dir)
    return Memory(
        rules=load_jsonl(root / RULES_FILE),
        tool_notes=load_jsonl(root / TOOL_NOTES_FILE),
        episodes=load_jsonl(root / EPISODES_FILE),
    )


def mark_demoted_on_disk(package_dir: Path | str, entry_ids: Iterable[str]) -> None:
    """Set ``demoted: true`` on the named rules. Display cache only."""
    ids = {str(i) for i in entry_ids}
    if not ids:
        return
    path = memory_dir(package_dir) / RULES_FILE
    rows = load_jsonl(path)
    if not rows:
        return
    for row in rows:
        if str(row.get("id")) in ids:
            row["demoted"] = True
    write_jsonl(path, rows)


# -- selection ----------------------------------------------------------


def _rule_score(rule: dict[str, Any], case_tokens: set[str]) -> float:
    keywords = rule.get("scope_keywords") or []
    keyword_tokens: set[str] = set()
    for keyword in keywords:
        keyword_tokens |= tokenize(keyword)
    if not keyword_tokens:
        return GLOBAL_RULE_SCORE
    return float(len(keyword_tokens & case_tokens))


def select_rules(
    rules: Iterable[dict[str, Any]],
    text: str,
    k: int = 12,
    demoted_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Top-K rules by keyword overlap with the case input.

    Rules demoted on disk or demoted in the ledger are excluded, as are rules
    with no keyword overlap at all.
    """
    demoted_ids = {str(i) for i in (demoted_ids or set())}
    case_tokens = tokenize(text)
    scored: list[tuple[float, float, float, str, dict[str, Any]]] = []
    for rule in rules:
        rule_id = str(rule.get("id", ""))
        if rule.get("demoted") is True or rule_id in demoted_ids:
            continue
        score = _rule_score(rule, case_tokens)
        if score <= 0:
            continue
        confidence = float(rule.get("confidence") or 0.0)
        net = float(rule.get("hits") or 0) - float(rule.get("misses") or 0)
        scored.append((-score, -confidence, -net, rule_id, rule))
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[: max(0, k)]]


def build_memory_block(
    tool_notes: Iterable[dict[str, Any]], rules: Iterable[dict[str, Any]]
) -> str:
    """Delimited memory block appended to the system prompt."""
    notes = list(tool_notes)
    selected = list(rules)
    if not notes and not selected:
        return ""
    lines = [
        MEMORY_BLOCK_START,
        "These entries were learned from earlier graded runs. Follow them unless the",
        "tool data in this case contradicts them.",
    ]
    if notes:
        lines.append("")
        lines.append("Tool notes:")
        for note in notes:
            tool = note.get("tool")
            prefix = f"({tool}) " if tool else ""
            lines.append(f"- [{note.get('id')}] {prefix}{note.get('note', '')}".rstrip())
    if selected:
        lines.append("")
        lines.append(f"Rules (top {len(selected)} by keyword match):")
        for rule in selected:
            lines.append(f"- [{rule.get('id')}] {rule.get('rule', '')}".rstrip())
    lines.append(MEMORY_BLOCK_END)
    return "\n".join(lines)


def inject_into_prompt(system_prompt: str, block: str) -> str:
    if not block:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{block}\n"


# -- hits / misses / demotion ------------------------------------------


@dataclass
class RuleUsage:
    hits: int = 0
    misses: int = 0

    @property
    def uses(self) -> int:
        return self.hits + self.misses


@dataclass(frozen=True)
class DemotionCandidate:
    entry_id: str
    hits: int
    misses: int


def usage_from_case_results(rows: Iterable[dict[str, Any]]) -> dict[str, RuleUsage]:
    """Credit hits/misses on injected rules from ``case_result`` payloads.

    ``passed`` comes from ``score.py`` via the ledger; nothing here consults the
    agent's own opinion of the run.
    """
    usage: dict[str, RuleUsage] = {}
    for row in rows:
        injected = row.get("rules_injected") or []
        if not injected:
            continue
        passed = bool(row.get("passed"))
        for entry_id in injected:
            entry = usage.setdefault(str(entry_id), RuleUsage())
            if passed:
                entry.hits += 1
            else:
                entry.misses += 1
    return usage


def demotion_candidates(
    usage: dict[str, RuleUsage],
    already_demoted: set[str] | None = None,
    min_uses: int = 4,
) -> list[DemotionCandidate]:
    """Rules used at least ``min_uses`` times with more misses than hits."""
    already_demoted = {str(i) for i in (already_demoted or set())}
    out = [
        DemotionCandidate(entry_id=entry_id, hits=stats.hits, misses=stats.misses)
        for entry_id, stats in usage.items()
        if entry_id not in already_demoted and stats.uses >= min_uses and stats.misses > stats.hits
    ]
    out.sort(key=lambda c: c.entry_id)
    return out
