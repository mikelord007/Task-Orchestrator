"""Patch: apply exactly one lever to produce a candidate version
(PLAN_ADDENDUM.md section D; lever mechanics section K/E).

`patch(agent_id, version, diagnosis)` copies `agents/<id>/v<N>/` to
`v<N+1>/` (or the next free candidate slot -- see `improve`, which allocates
a fresh, never-reused integer per attempt so a rejected candidate's directory
is never overwritten), applies the diagnosis's lever, writes
`CHANGES.diff` (unified diff `v<N>` -> the candidate), and emits
`fix_proposed` with the full section A payload.

Lever mechanics:

* `memory` -- calls `reflect()` on the diagnosis's failing group and appends
  the proposals to `memory/rules.jsonl` / `memory/tool_notes.jsonl`, plus one
  `episodes.jsonl` line. If reflection yields nothing (no readable
  transcripts, or the model proposed nothing usable), this falls back to the
  `prompt` lever so the attempt still produces a real, gate-able change.
* `tools` -- rewrites the target tool's `TOOL["description"]` in the
  package's own `tools/<name>.py` copy (never `backend/toolbox/`), per
  section K priority (1): "rewrite a tool's description or parameter names".
  The target tool is inferred from which tool the failing group's
  transcripts actually called most.
* `prompt` -- appends a targeted "## Lesson" section to `prompt.md`.
* `orchestration` -- flips `agent.yaml`'s `orchestration` between `single`
  and `planner_worker` (the contract's only two modes) and records why.
"""

from __future__ import annotations

import ast
import difflib
import json
import pprint
import shutil
import sqlite3
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from backend.architect.llm_client import CompleteFn
from backend.improver.diagnose import Diagnosis
from backend.improver.grouping import failing_case_trials, resolve_transcript_path
from backend.improver.reflect import reflect
from backend.runtime.package import DEFAULT_AGENTS_DIR
from contracts.agent import Episode, MemoryRule, ToolNote, new_entry_id
from contracts.events import Lever
from contracts.transcript import load_transcript

__all__ = ["PatchError", "patch"]

MEMORY_FILES = ("rules.jsonl", "tool_notes.jsonl", "episodes.jsonl")


class PatchError(RuntimeError):
    """The diagnosis could not be turned into a real, on-disk change."""


def _package_dir(agents_dir: str | Path, agent_id: str, version: int) -> Path:
    return Path(agents_dir) / agent_id / f"v{version}"


def _copy_package(src: Path, dst: Path) -> None:
    if dst.exists():
        raise PatchError(f"candidate directory already exists: {dst}")
    shutil.copytree(src, dst)


def _bump_agent_yaml_version(package_dir: Path, candidate_version: int) -> None:
    yaml_path = package_dir / "agent.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    data["version"] = candidate_version
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _unified_diff(before: str, after: str, path_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path_label}",
            tofile=f"b/{path_label}",
        )
    )


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read(path)
    body = existing
    if body and not body.endswith("\n"):
        body += "\n"
    for row in rows:
        body += json.dumps(row, default=str) + "\n"
    path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# memory lever
# --------------------------------------------------------------------------


def _apply_memory(
    *,
    package_dir: Path,
    candidate_version: int,
    diagnosis: Diagnosis,
    proposals: list[Any],
    issue_id: str | None,
    emit: Any,
    agent_id: str,
) -> tuple[list[str], str, str]:
    mem_dir = package_dir / "memory"
    rules_path = mem_dir / "rules.jsonl"
    notes_path = mem_dir / "tool_notes.jsonl"
    episodes_path = mem_dir / "episodes.jsonl"

    before = {p.name: _read(p) for p in (rules_path, notes_path, episodes_path)}
    source = "issue" if issue_id else "reflection"

    new_rules: list[dict[str, Any]] = []
    new_notes: list[dict[str, Any]] = []
    written: list[tuple[str, dict[str, Any]]] = []  # (kind, event payload extras)

    for proposal in proposals:
        if proposal.kind == "rule":
            row = MemoryRule(
                id=new_entry_id("rule"),
                rule=proposal.rule or "",
                scope_keywords=proposal.scope_keywords,
                evidence_case_ids=proposal.evidence_case_ids,
                confidence=0.5,
                hits=0,
                misses=0,
                created_version=candidate_version,
                source=source,  # type: ignore[arg-type]
                demoted=False,
            ).model_dump(mode="json")
            new_rules.append(row)
            written.append(("rule", row))
        else:
            row = ToolNote(
                id=new_entry_id("tool_note"),
                tool=proposal.tool or "",
                note=proposal.note or "",
                evidence=proposal.evidence or "",
                created_version=candidate_version,
            ).model_dump(mode="json")
            new_notes.append(row)
            written.append(("tool_note", row))

    if new_rules:
        _append_jsonl(rules_path, new_rules)
    if new_notes:
        _append_jsonl(notes_path, new_notes)

    one_liner = (diagnosis.hypothesis or "Reflection produced new memory entries.").splitlines()[0][
        :280
    ]
    episode_row = Episode(
        version=candidate_version,
        run_id=f"reflect_{uuid.uuid4().hex[:8]}",
        one_line_reflection=one_liner,
    ).model_dump(mode="json")
    _append_jsonl(episodes_path, [episode_row])
    written.append(("episode", episode_row))

    for kind, row in written:
        evidence = (
            row.get("evidence_case_ids") if kind == "rule" else diagnosis.failing_group.case_ids
        )
        emit(
            "memory_written",
            agent_id=agent_id,
            agent_version=candidate_version,
            lever=Lever.memory.value,
            payload={
                "entry_id": row["id"] if kind != "episode" else f"episode_{row['run_id']}",
                "kind": kind,
                "source": source,
                "evidence_case_ids": list(evidence or []),
                "version": candidate_version,
            },
        )

    files_touched = []
    diff_parts = []
    for path, label in (
        (rules_path, "memory/rules.jsonl"),
        (notes_path, "memory/tool_notes.jsonl"),
        (episodes_path, "memory/episodes.jsonl"),
    ):
        after_text = _read(path)
        if after_text != before[path.name]:
            files_touched.append(label)
            diff_parts.append(_unified_diff(before[path.name], after_text, label))

    diff_summary = f"memory: +{len(new_rules)} rule(s), +{len(new_notes)} tool note(s), +1 episode"
    diff_text = "".join(diff_parts) or f"# {diff_summary}\n"
    return files_touched, diff_text, diff_summary


# --------------------------------------------------------------------------
# tools lever
# --------------------------------------------------------------------------


def _tool_modules(tools_dir: Path) -> dict[str, str]:
    """``tool name -> module stem`` for every ``tools/*.py`` in the package.

    ``backend.toolbox.registry.write_agent_tool`` names the file after the
    tool, so the two normally match -- but an LLM-authored glue tool, or a
    hand-written package, need not follow that convention, and a transcript
    only ever records the *tool* name. Both spellings map to the stem so
    either one finds the file to edit.
    """
    modules: dict[str, str] = {}
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        modules.setdefault(path.stem, path.stem)
        try:
            assign = _find_tool_assign(ast.parse(path.read_text(encoding="utf-8")))
            declared = ast.literal_eval(assign.value).get("name") if assign is not None else None
        except (OSError, SyntaxError, ValueError):
            declared = None
        if isinstance(declared, str) and declared:
            modules[declared] = path.stem
    return modules


def _infer_target_tool(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    diagnosis: Diagnosis,
    tools_dir: Path,
    root: str | Path,
) -> str | None:
    modules = _tool_modules(tools_dir)
    if not modules:
        return None

    counts: Counter[str] = Counter()
    for _case_id, _trial, transcript_path in failing_case_trials(
        conn, agent_id, version, set(diagnosis.failing_group.case_ids)
    ):
        full_path = resolve_transcript_path(root, transcript_path)
        try:
            transcript = load_transcript(full_path)
        except (OSError, ValueError):
            continue
        for step in transcript.steps:
            kind = step.kind.value if hasattr(step.kind, "value") else step.kind
            if kind == "tool_call" and step.tool in modules:
                counts[step.tool] += 1
    if counts:
        return modules[counts.most_common(1)[0][0]]

    text = f"{diagnosis.metric_signal or ''} {diagnosis.proposed_change}".lower()
    for name in sorted(modules, key=len, reverse=True):
        if name.lower() in text:
            return modules[name]
    stems = set(modules.values())
    return next(iter(stems)) if len(stems) == 1 else None


def _find_tool_assign(tree: ast.Module) -> ast.Assign | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOOL" for t in node.targets
        ):
            return node
    return None


def _apply_tools(
    *, package_dir: Path, candidate_version: int, diagnosis: Diagnosis, tool_name: str
) -> tuple[list[str], str, str]:
    path = package_dir / "tools" / f"{tool_name}.py"
    source = _read(path)
    tree = ast.parse(source)
    assign = _find_tool_assign(tree)
    if assign is None:
        raise PatchError(f"{path}: no TOOL = {{...}} assignment found")
    tool_dict = ast.literal_eval(assign.value)

    note = (diagnosis.proposed_change or diagnosis.diagnosis).strip()
    addition = f"\n\nLesson from v{candidate_version} (improver, lever=tools): {note}"
    tool_dict["description"] = str(tool_dict.get("description", "")).rstrip() + addition

    segment = ast.get_source_segment(source, assign)
    if segment is None:
        raise PatchError(f"{path}: could not locate the TOOL assignment's source text")
    new_segment = f"TOOL = {pprint.pformat(tool_dict, width=88, sort_dicts=False)}"
    new_source = source.replace(segment, new_segment, 1)
    path.write_text(new_source, encoding="utf-8")

    label = f"tools/{tool_name}.py"
    diff = _unified_diff(source, new_source, label)
    diff_summary = f"tools: rewrote {tool_name}'s description"
    return [label], diff, diff_summary


# --------------------------------------------------------------------------
# prompt lever
# --------------------------------------------------------------------------


def _apply_prompt(
    *, package_dir: Path, candidate_version: int, diagnosis: Diagnosis
) -> tuple[list[str], str, str]:
    path = package_dir / "prompt.md"
    before = _read(path)
    change = (diagnosis.proposed_change or diagnosis.diagnosis).strip()
    section = f"\n\n## Lesson (v{candidate_version})\n\n{change}\n"
    after = before.rstrip() + section
    path.write_text(after, encoding="utf-8")
    diff = _unified_diff(before, after, "prompt.md")
    return ["prompt.md"], diff, "prompt: appended a targeted lesson section"


# --------------------------------------------------------------------------
# orchestration lever
# --------------------------------------------------------------------------


def _apply_orchestration(
    *, package_dir: Path, candidate_version: int, diagnosis: Diagnosis
) -> tuple[list[str], str, str]:
    path = package_dir / "agent.yaml"
    before = _read(path)
    data = yaml.safe_load(before) or {}
    old_mode = data.get("orchestration", "single")
    new_mode = "planner_worker" if old_mode == "single" else "single"
    data["orchestration"] = new_mode
    data["orchestration_reason"] = (diagnosis.proposed_change or diagnosis.diagnosis).strip()[:500]
    after = yaml.safe_dump(data, sort_keys=False)
    path.write_text(after, encoding="utf-8")
    diff = _unified_diff(before, after, "agent.yaml")
    return ["agent.yaml"], diff, f"orchestration: {old_mode} -> {new_mode}"


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def patch(
    agent_id: str,
    version: int,
    diagnosis: Diagnosis,
    *,
    candidate_version: int | None = None,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    agents_dir: str | Path = DEFAULT_AGENTS_DIR,
    root: str | Path = ".",
    model: str | None = None,
    complete: CompleteFn | None = None,
    emit: Any | None = None,
    issue_id: str | None = None,
) -> int:
    """Apply `diagnosis`'s lever, writing a new agent package version.

    Returns the candidate version number. Emits `fix_proposed`. Raises
    `PatchError` if the lever cannot be applied to this package (e.g. no
    inferable target tool for `lever=tools`) -- callers should try the next
    diagnosis rather than treat this as fatal.
    """
    from backend.ledger.emit import emit as default_emit_fn

    emit = emit or default_emit_fn
    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)

    try:
        candidate = candidate_version if candidate_version is not None else version + 1
        src_dir = _package_dir(agents_dir, agent_id, version)
        dst_dir = _package_dir(agents_dir, agent_id, candidate)
        _copy_package(src_dir, dst_dir)
        _bump_agent_yaml_version(dst_dir, candidate)

        lever = diagnosis.lever
        files_touched: list[str] = []
        diff_text = ""
        diff_summary = ""

        if lever == Lever.memory.value:
            proposals = reflect(
                agent_id,
                version,
                diagnosis.failing_group,
                conn=conn,
                root=root,
                model=model,
                complete=complete,
            )
            if not proposals:
                lever = Lever.prompt.value
                files_touched, diff_text, diff_summary = _apply_prompt(
                    package_dir=dst_dir, candidate_version=candidate, diagnosis=diagnosis
                )
                diff_summary = "memory: reflection produced nothing; fell back to " + diff_summary
            else:
                files_touched, diff_text, diff_summary = _apply_memory(
                    package_dir=dst_dir,
                    candidate_version=candidate,
                    diagnosis=diagnosis,
                    proposals=proposals,
                    issue_id=issue_id,
                    emit=emit,
                    agent_id=agent_id,
                )
        elif lever == Lever.tools.value:
            tool_name = _infer_target_tool(
                conn, agent_id, version, diagnosis, dst_dir / "tools", root
            )
            if tool_name is None:
                lever = Lever.prompt.value
                files_touched, diff_text, diff_summary = _apply_prompt(
                    package_dir=dst_dir, candidate_version=candidate, diagnosis=diagnosis
                )
                diff_summary = "tools: no target tool inferable; fell back to " + diff_summary
            else:
                files_touched, diff_text, diff_summary = _apply_tools(
                    package_dir=dst_dir,
                    candidate_version=candidate,
                    diagnosis=diagnosis,
                    tool_name=tool_name,
                )
        elif lever == Lever.prompt.value:
            files_touched, diff_text, diff_summary = _apply_prompt(
                package_dir=dst_dir, candidate_version=candidate, diagnosis=diagnosis
            )
        elif lever == Lever.orchestration.value:
            files_touched, diff_text, diff_summary = _apply_orchestration(
                package_dir=dst_dir, candidate_version=candidate, diagnosis=diagnosis
            )
        else:
            raise PatchError(f"patch cannot apply lever {lever!r}")

        diff_path = dst_dir / "CHANGES.diff"
        diff_path.write_text(diff_text or f"# {diff_summary}\n", encoding="utf-8")
        diff_path_str = str(diff_path).replace("\\", "/")

        emit(
            "fix_proposed",
            agent_id=agent_id,
            agent_version=candidate,
            lever=lever,
            from_version=version,
            to_version=candidate,
            failing_group=diagnosis.failing_group.model_dump(mode="json"),
            hypothesis=diagnosis.hypothesis,
            diagnosis=diagnosis.diagnosis,
            diff_path=diff_path_str,
            diff_summary=diff_summary,
            files_touched=files_touched,
            issue_id=issue_id,
            metric_signal=diagnosis.metric_signal if lever == Lever.tools.value else None,
        )
        return candidate
    finally:
        if owns_conn:
            conn.close()
