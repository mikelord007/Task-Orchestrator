"""Pure reads: group a train run's failures into `FailingGroup`s.

Shared by `diagnose` (ranks the top-3 groups) and `reflect` (analyzes one
group's evidence). Nothing here calls an LLM or writes anything.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.ledger.query import Event, agent_row, case_results, latest_run
from backend.runtime.scoring import DEFAULT_EVALUATORS_DIR, evaluator_dir, load_cases
from contracts.events import FailingGroup

__all__ = [
    "TRAIN_SPLIT",
    "failing_case_trials",
    "group_train_failures",
    "load_case_index",
    "load_case_tags",
    "resolve_evaluator_path",
]

TRAIN_SPLIT = "train"


def resolve_evaluator_path(
    conn: sqlite3.Connection,
    agent_id: str,
    evaluators_dir: str | Path = DEFAULT_EVALUATORS_DIR,
) -> Path:
    """The evaluator directory for `agent_id`, from the `agents` table."""
    row = agent_row(conn, agent_id)
    evaluator_id = (row or {}).get("evaluator_id")
    if not evaluator_id:
        raise ValueError(f"agent {agent_id!r} has no evaluator_id on record")
    return evaluator_dir(str(evaluator_id), evaluators_dir)


def load_case_tags(evaluator_path: str | Path) -> dict[str, list[str]]:
    """`case_id -> tags[]` from every split's `cases.jsonl` rows."""
    cases = load_cases(evaluator_path)
    return {str(c.get("id")): list(c.get("tags") or []) for c in cases}


def load_case_index(evaluator_path: str | Path) -> dict[str, dict[str, Any]]:
    """`case_id -> full case row` (input, expected, tags, split)."""
    cases = load_cases(evaluator_path)
    return {str(c.get("id")): c for c in cases}


def group_train_failures(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    evaluator_path: str | Path,
) -> list[FailingGroup]:
    """Group the version's latest train run's failing (task, trial) rows by
    `failure_signature`, ranked by failing-trial count descending.

    A task failing 2 of its 3 trials contributes 2 to its signature's `count`
    and appears once in `case_ids` -- this is the "weight" the brief
    describes, expressed as a trial count rather than a fraction so `count`
    stays the plain int the `FailingGroup` contract wants. `drift:*`
    signatures fall out of this the same way any other signature does: they
    are not merged with anything else because the string itself is distinct.
    """
    run = latest_run(conn, agent_id, version, TRAIN_SPLIT)
    if run is None:
        return []
    results = case_results(conn, run.run_id)
    tags_by_case = load_case_tags(evaluator_path)

    case_ids_by_sig: dict[str, set[str]] = defaultdict(set)
    count_by_sig: Counter[str] = Counter()
    tag_votes_by_sig: dict[str, Counter[str]] = defaultdict(Counter)

    for event in results:
        if event.get("passed"):
            continue
        case_id = str(event.get("case_id"))
        signature = event.get("failure_signature") or "unknown_failure"
        case_ids_by_sig[signature].add(case_id)
        count_by_sig[signature] += 1
        for tag in tags_by_case.get(case_id, []):
            tag_votes_by_sig[signature][tag] += 1

    groups: list[FailingGroup] = []
    for signature, case_ids in case_ids_by_sig.items():
        votes = tag_votes_by_sig[signature]
        tag: str | None = None
        if votes:
            top_count = votes.most_common(1)[0][1]
            tag = sorted(t for t, v in votes.items() if v == top_count)[0]
        groups.append(
            FailingGroup(
                signature=signature,
                tag=tag,
                case_ids=sorted(case_ids),
                count=count_by_sig[signature],
            )
        )
    groups.sort(key=lambda g: (-g.count, g.signature))
    return groups


def failing_case_trials(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    case_ids: set[str],
    *,
    max_cases: int | None = None,
) -> list[tuple[str, int, str]]:
    """`(case_id, trial, transcript_path)` for one failing trial per case in
    `case_ids` -- the first failing trial found, oldest-first. Only cases
    that actually failed a trial in the version's latest train run are
    returned (a case_id from a stale group that later fully passed yields
    nothing for it)."""
    run = latest_run(conn, agent_id, version, TRAIN_SPLIT)
    if run is None:
        return []
    seen: set[str] = set()
    out: list[tuple[str, int, str]] = []
    for event in case_results(conn, run.run_id):
        case_id = str(event.get("case_id"))
        if case_id not in case_ids or event.get("passed") or case_id in seen:
            continue
        path = event.get("transcript_path")
        if not path:
            continue
        out.append((case_id, int(event.get("trial") or 0), str(path)))
        seen.add(case_id)
        if max_cases is not None and len(out) >= max_cases:
            break
    return out


def latest_train_event(conn: sqlite3.Connection, agent_id: str, version: int) -> Event | None:
    """The `run_finished` event of the version's latest train run, if any."""
    run = latest_run(conn, agent_id, version, TRAIN_SPLIT)
    return run.finished if run else None


def resolve_transcript_path(root: str | Path, transcript_path: str) -> Path:
    """`transcript_path` as an absolute-or-root-relative `Path`.

    `case_result.transcript_path` is written relative to the repo root by the
    runtime; a caller with a different working directory (most tests) passes
    `root` to resolve it."""
    path = Path(transcript_path)
    return path if path.is_absolute() else Path(root) / path
