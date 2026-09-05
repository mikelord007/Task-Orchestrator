"""Metrics over the event ledger.

Every function here is a **pure read**: it takes a sqlite connection (plus, for
a few of them, a filesystem root) and returns a value. Nothing in this module
writes to any table, caches to disk, or stores a derived status -- PLAN.md
sections 2.4, 2.8 and 4.1, reaffirmed by PLAN_ADDENDUM.md sec 0. Empty input
yields honest nulls and empty collections, never a zero pretending to be data.

Terminology (PLAN_ADDENDUM.md sec J): a **task** is one evaluator case, a
**trial** is one repeated execution of a task (``case_result.trial``; ``repeat``
is accepted as an alias for events written before the rename), and the
**grader** is ``score.py``.

Definitions that matter (PLAN_ADDENDUM.md sec A/B):

* **pass@1** -- mean per-trial pass rate over tasks: for a run with ``trials =
  T``, this is total passes over ``tasks * T``. Equivalently the mean over
  tasks of (passes / T), or the mean over trials of (tasks passed that trial /
  tasks) -- both give the same number.
* **pass^k** (k = trials) -- the fraction of tasks that passed *every* trial.
  Those tasks are the **stable pass set**; the gate accepts/rejects on pass^k.
* Both ``pass_at_1`` and ``pass_pow_k`` report ``std``/``min``/``max`` computed
  over the same underlying per-trial pass-rate array (one rate per trial index:
  tasks-passed-in-that-trial / task-count) -- they differ only in what their
  ``mean`` measures.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from backend.ledger.query import (
    Event,
    agent_row,
    agent_rows,
    case_results,
    events,
    issue_status,
    latest_run,
    runs,
)

__all__ = [
    "DEFAULT_DRIFT_TOKEN_BUDGET",
    "compare",
    "cost_per_run",
    "drift_stats",
    "fix_cards",
    "fix_diff",
    "fixes_by_lever",
    "graduated_count",
    "insights",
    "insights_compare",
    "issue_stats",
    "latency_percentiles",
    "lessons_count",
    "markers",
    "memory_by_version",
    "pass_at_1",
    "pass_pow_k",
    "regressions_caught",
    "rule_stats",
    "saturated",
    "series_by_version",
    "stable_pass_set",
    "tool_call_stats",
    "zero_pass_tasks",
]

DEFAULT_DRIFT_TOKEN_BUDGET = 20_000

#: A task must be at 0% across this many consecutive finished train runs
#: before it is flagged (PLAN_ADDENDUM.md sec J: "0% is usually a broken task").
ZERO_PASS_WINDOW = 3

#: Train pass@1 threshold and run count for "capability suite saturated".
SATURATION_THRESHOLD = 0.95
SATURATION_WINDOW = 2

#: Issue statuses that count as closed for :func:`issue_stats`.
CLOSED_ISSUE_STATUSES = frozenset({"fixed", "wontfix", "closed"})

_EMPTY_PASS_STAT: dict[str, Any] = {
    "mean": None,
    "std": None,
    "min": None,
    "max": None,
    "trials": None,
    "task_count": 0,
}

_SPLIT_ORDER = {"train": 0, "holdout": 1}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pstdev(values: Sequence[float]) -> float | None:
    """Population standard deviation (the band in the charts), or None."""
    if not values:
        return None
    mu = sum(values) / len(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))


def _percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolation percentile; ``pct`` in [0, 1]."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * pct
    low = math.floor(k)
    high = math.ceil(k)
    if low == high:
        return float(ordered[int(k)])
    return float(ordered[low] * (high - k) + ordered[high] * (k - low))


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_key(split: str | None) -> tuple[int, str]:
    return _SPLIT_ORDER.get(split or "", 2), split or ""


def repo_root(root: str | Path | None = None) -> Path:
    """Filesystem root that ``runs/``, ``agents/`` and ``evaluators/`` live under."""
    if root is not None:
        return Path(root)
    env = os.environ.get("TASK_ORCHESTRATOR_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _resolve(path: str | None, root: str | Path | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else repo_root(root) / candidate


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def drift_token_budget() -> int:
    """``DRIFT_TOKEN_BUDGET`` from the environment (PLAN.md section 3)."""
    raw = os.environ.get("DRIFT_TOKEN_BUDGET")
    value = _int(raw) if raw else None
    return value if value is not None else DEFAULT_DRIFT_TOKEN_BUDGET


# --------------------------------------------------------------------------
# trial-level pass statistics (pass@1 / pass^k)
# --------------------------------------------------------------------------


def _results_by_task(results: Iterable[Event]) -> dict[str, list[Event]]:
    by_task: dict[str, list[Event]] = {}
    for event in results:
        case_id = event.get("case_id")
        if case_id is None:
            continue
        by_task.setdefault(str(case_id), []).append(event)
    return by_task


def _results_by_trial(results: Iterable[Event]) -> dict[int, list[Event]]:
    by_trial: dict[int, list[Event]] = {}
    for event in results:
        if event.get("case_id") is None:
            continue
        trial = event.trial()
        by_trial.setdefault(trial if trial is not None else 0, []).append(event)
    return by_trial


def _stable_task_ids(by_task: dict[str, list[Event]]) -> set[str]:
    """Tasks that passed in every trial present for them."""
    return {
        task_id
        for task_id, rows in by_task.items()
        if rows and all(bool(e.get("passed")) for e in rows)
    }


def _trial_rates(results: Sequence[Event]) -> tuple[list[float], int]:
    """Per-trial pass rates (tasks-passed-in-that-trial / task-count) and task count."""
    by_task = _results_by_task(results)
    by_trial = _results_by_trial(results)
    task_count = len(by_task)
    if task_count == 0:
        return [], 0
    rates = [
        sum(1 for e in rows if e.get("passed")) / task_count
        for _, rows in sorted(by_trial.items())
    ]
    return rates, task_count


def _pass_stat(
    results: Sequence[Event], declared_trials: int | None, *, mean: float | None
) -> dict[str, Any]:
    """Shared shape for pass@1 and pass^k: same std/min/max, different mean."""
    rates, task_count = _trial_rates(results)
    if task_count == 0:
        return dict(_EMPTY_PASS_STAT)
    return {
        "mean": mean,
        "std": _pstdev(rates),
        "min": min(rates) if rates else None,
        "max": max(rates) if rates else None,
        "trials": declared_trials if declared_trials is not None else len(rates),
        "task_count": task_count,
    }


def pass_at_1(
    conn: sqlite3.Connection, agent_id: str, version: int, split: str
) -> dict[str, Any]:
    """pass@1 of the latest finished run of ``(agent_id, version, split)``.

    Returns ``{mean, std, min, max, trials, task_count}``; ``mean`` is the mean
    per-trial pass rate over tasks. With no such run every statistic is
    ``None`` and ``task_count`` is 0.
    """
    run = latest_run(conn, agent_id, version, split)
    if run is None:
        return dict(_EMPTY_PASS_STAT)
    results = case_results(conn, run.run_id)
    rates, task_count = _trial_rates(results)
    if task_count == 0:
        return dict(_EMPTY_PASS_STAT)
    return _pass_stat(results, _int(run.trials), mean=_mean(rates))


def pass_pow_k(
    conn: sqlite3.Connection, agent_id: str, version: int, split: str
) -> dict[str, Any]:
    """pass^k of the latest finished run of ``(agent_id, version, split)``.

    ``mean`` is the fraction of tasks that passed *every* trial (the stable
    pass rate); ``std``/``min``/``max`` are the same per-trial-rate spread
    reported by :func:`pass_at_1`, so the two series share an error band.
    """
    run = latest_run(conn, agent_id, version, split)
    if run is None:
        return dict(_EMPTY_PASS_STAT)
    results = case_results(conn, run.run_id)
    by_task = _results_by_task(results)
    task_count = len(by_task)
    if task_count == 0:
        return dict(_EMPTY_PASS_STAT)
    stable = len(_stable_task_ids(by_task))
    return _pass_stat(results, _int(run.trials), mean=stable / task_count)


def stable_pass_set(conn: sqlite3.Connection, agent_id: str, version: int) -> set[str]:
    """Train tasks that passed in *every* trial of the latest train run.

    This is the set the gate protects; a flaky task is never in it and so can
    never be reported as a regression.
    """
    run = latest_run(conn, agent_id, version, "train")
    if run is None:
        return set()
    return _stable_task_ids(_results_by_task(case_results(conn, run.run_id)))


def _stable_task_ids_for(
    conn: sqlite3.Connection, agent_id: str, version: int, split: str
) -> set[str]:
    run = latest_run(conn, agent_id, version, split)
    if run is None:
        return set()
    return _stable_task_ids(_results_by_task(case_results(conn, run.run_id)))


# --------------------------------------------------------------------------
# cost and latency
# --------------------------------------------------------------------------


def _run_costs(results: Sequence[Event]) -> tuple[float | None, float | None]:
    costs = [c for c in (_num(e.get("cost_usd")) for e in results) if c is not None]
    if not costs:
        return None, None
    total = sum(costs)
    task_count = len(_results_by_task(results))
    return total, (total / task_count if task_count else None)


def cost_per_run(
    conn: sqlite3.Connection, agent_id: str, version: int, split: str
) -> float | None:
    """Total USD spent by the latest finished run of ``(agent, version, split)``.

    "Per run" means the whole run: every task at every trial. ``None`` when the
    run does not exist or recorded no cost.
    """
    run = latest_run(conn, agent_id, version, split)
    if run is None:
        return None
    return _run_costs(case_results(conn, run.run_id))[0]


def latency_percentiles(
    conn: sqlite3.Connection, agent_id: str, version: int, split: str
) -> dict[str, float | None]:
    """``{p50, p95}`` of per-task-execution latency in the latest finished run."""
    run = latest_run(conn, agent_id, version, split)
    if run is None:
        return {"p50": None, "p95": None}
    latencies = [
        v
        for v in (_num(e.get("latency_ms")) for e in case_results(conn, run.run_id))
        if v is not None
    ]
    return {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)}


# --------------------------------------------------------------------------
# fixes, issues, lessons
# --------------------------------------------------------------------------


def _proposals_by_version(conn: sqlite3.Connection, agent_id: str) -> dict[int, Event]:
    """``to_version -> fix_proposed`` (the newest proposal wins)."""
    out: dict[int, Event] = {}
    for event in events(conn, kind="fix_proposed", agent_id=agent_id):
        to_version = _int(event.get("to_version"))
        if to_version is not None:
            out[to_version] = event
    return out


def _lever_of(proposal: Event | None, outcome: Event | None = None) -> str | None:
    for event in (proposal, outcome):
        if event is None:
            continue
        if event.lever:
            return event.lever
        lever = event.get("lever")
        if lever:
            return str(lever)
    return None


def fixes_by_lever(conn: sqlite3.Connection, agent_id: str) -> dict[str, int]:
    """Count of **accepted** fixes per lever (``memory|tools|prompt|orchestration|routing|grader``).

    Rejected attempts are not counted here -- they are visible as fix cards and
    in :func:`regressions_caught`. A ``grader`` fix (correcting the grader
    itself) is counted like any other lever but is excluded from the
    improvement curve by consumers, per PLAN_ADDENDUM.md sec J.
    """
    proposals = _proposals_by_version(conn, agent_id)
    counts: dict[str, int] = {}
    for event in events(conn, kind="fix_accepted", agent_id=agent_id):
        to_version = _int(event.get("to_version"))
        lever = _lever_of(
            proposals.get(to_version) if to_version is not None else None, event
        )
        key = lever or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def regressions_caught(conn: sqlite3.Connection, agent_id: str) -> int:
    """Number of ``fix_rejected`` events whose reason is ``regression``."""
    return sum(
        1
        for event in events(conn, kind="fix_rejected", agent_id=agent_id)
        if event.get("reason") == "regression"
    )


def issue_stats(conn: sqlite3.Connection, agent_id: str) -> dict[str, int]:
    """``{open, closed}`` over the issues opened for this agent.

    Issue ids come from ``issue_opened`` events; the status comes from the
    ``issues`` table. An id with no row yet counts as open -- nothing has
    recorded it being closed.
    """
    issue_ids = []
    for event in events(conn, kind="issue_opened", agent_id=agent_id):
        issue_id = event.get("issue_id")
        if issue_id is not None:
            issue_ids.append(str(issue_id))
    unique = list(dict.fromkeys(issue_ids))
    statuses = issue_status(conn, unique)
    closed = sum(
        1 for i in unique if (statuses.get(i) or "").lower() in CLOSED_ISSUE_STATUSES
    )
    return {"open": len(unique) - closed, "closed": closed}


def lessons_count(conn: sqlite3.Connection) -> int:
    """Distinct lessons recorded in the playbook, across every agent."""
    seen: set[str] = set()
    unnamed = 0
    for event in events(conn, kind="lesson_recorded"):
        lesson_id = event.get("lesson_id")
        if lesson_id is None:
            unnamed += 1
        else:
            seen.add(str(lesson_id))
    return len(seen) + unnamed


# --------------------------------------------------------------------------
# drift
# --------------------------------------------------------------------------


def drift_stats(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any]:
    """``{count_by_kind, tokens_saved, cases_recovered_by_nudge, count_by_version}``.

    ``tokens_saved`` sums ``DRIFT_TOKEN_BUDGET - tokens_at_detection`` over
    aborted trials (never negative). ``cases_recovered_by_nudge`` counts
    (run, task, trial) triples that were nudged and then passed.
    """
    budget = drift_token_budget()
    drift_events = events(conn, kind="drift_detected", agent_id=agent_id)

    count_by_kind: dict[str, int] = {}
    count_by_version: dict[int, int] = {}
    tokens_saved = 0.0
    nudged: set[tuple[str | None, str, int]] = set()

    for event in drift_events:
        kind = str(event.get("kind") or "unknown")
        count_by_kind[kind] = count_by_kind.get(kind, 0) + 1
        version = _int(event.agent_version)
        if version is not None:
            count_by_version[version] = count_by_version.get(version, 0) + 1

        action = event.get("action")
        if action == "abort":
            at_detection = _num(event.get("tokens_at_detection"))
            if at_detection is not None:
                tokens_saved += max(0.0, budget - at_detection)
        elif action == "nudge":
            case_id = event.get("case_id")
            if case_id is not None:
                trial = event.trial() or 0
                nudged.add((event.run_id, str(case_id), trial))

    recovered = 0
    if nudged:
        for event in events(conn, kind="case_result", agent_id=agent_id):
            case_id = event.get("case_id")
            if case_id is None or not event.get("passed"):
                continue
            key = (event.run_id, str(case_id), event.trial() or 0)
            if key in nudged:
                recovered += 1

    return {
        "count_by_kind": count_by_kind,
        "tokens_saved": int(tokens_saved),
        "cases_recovered_by_nudge": recovered,
        "count_by_version": {str(k): v for k, v in sorted(count_by_version.items())},
    }


# --------------------------------------------------------------------------
# series and chart annotations
# --------------------------------------------------------------------------


def _finished_version_splits(
    conn: sqlite3.Connection, agent_id: str
) -> list[tuple[int, str]]:
    pairs = {
        (run.version, run.split)
        for run in runs(conn, agent_id)
        if run.version is not None and run.split
    }
    return sorted(pairs, key=lambda p: (p[0], _split_key(p[1])))


def series_by_version(
    conn: sqlite3.Connection, agent_id: str
) -> dict[str, list[dict[str, Any]]]:
    """pass@1 / pass^k / cost / latency series, one row per (version, split).

    Only versions with a *finished* run appear; train and holdout are separate
    rows so the charts can draw two lines.
    """
    pass_at_1_rows: list[dict[str, Any]] = []
    pass_pow_k_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []

    for version, split in _finished_version_splits(conn, agent_id):
        run = latest_run(conn, agent_id, version, split)
        if run is None:
            continue
        results = case_results(conn, run.run_id)
        rates, task_count = _trial_rates(results)
        if task_count == 0:
            continue

        pass_at_1_rows.append(
            {
                "version": version,
                "split": split,
                **_pass_stat(results, _int(run.trials), mean=_mean(rates)),
            }
        )
        by_task = _results_by_task(results)
        stable_mean = len(_stable_task_ids(by_task)) / task_count
        pass_pow_k_rows.append(
            {
                "version": version,
                "split": split,
                **_pass_stat(results, _int(run.trials), mean=stable_mean),
            }
        )

        total, per_task = _run_costs(results)
        cost_rows.append(
            {
                "version": version,
                "split": split,
                "cost_per_run": total,
                "cost_per_task": per_task,
            }
        )

        latencies = [
            v for v in (_num(e.get("latency_ms")) for e in results) if v is not None
        ]
        latency_rows.append(
            {
                "version": version,
                "split": split,
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
            }
        )

    return {
        "pass_at_1_by_version": pass_at_1_rows,
        "pass_pow_k_by_version": pass_pow_k_rows,
        "cost_by_version": cost_rows,
        "latency_by_version": latency_rows,
    }


def markers(conn: sqlite3.Connection, agent_id: str) -> list[dict[str, Any]]:
    """Chart annotations: issues, fixes, drift clusters and memory demotions.

    Drift is clustered by version -- one marker per version carrying the total
    and the per-kind breakdown -- because individual drift events are far too
    dense to annotate a chart with.
    """
    proposals = _proposals_by_version(conn, agent_id)
    out: list[dict[str, Any]] = []

    for event in events(conn, kind="issue_opened", agent_id=agent_id):
        out.append(
            {
                "kind": "issue_opened",
                "ts": event.ts,
                "version": _int(event.agent_version),
                "issue_id": event.get("issue_id"),
                "title": event.get("title"),
                "source": event.get("source"),
            }
        )

    for kind in ("fix_accepted", "fix_rejected"):
        for event in events(conn, kind=kind, agent_id=agent_id):
            to_version = _int(event.get("to_version"))
            proposal = proposals.get(to_version) if to_version is not None else None
            out.append(
                {
                    "kind": kind,
                    "ts": event.ts,
                    "version": to_version
                    if to_version is not None
                    else _int(event.agent_version),
                    "to_version": to_version,
                    "from_version": _int(proposal.get("from_version"))
                    if proposal
                    else None,
                    "lever": _lever_of(proposal, event),
                    "hypothesis": proposal.get("hypothesis") if proposal else None,
                    "diagnosis": proposal.get("diagnosis") if proposal else None,
                    "metric_signal": proposal.get("metric_signal")
                    if proposal
                    else None,
                    "reason": event.get("reason") if kind == "fix_rejected" else None,
                }
            )

    for event in events(conn, kind="memory_demoted", agent_id=agent_id):
        version = _int(event.get("version"))
        out.append(
            {
                "kind": "memory_demoted",
                "ts": event.ts,
                "version": version
                if version is not None
                else _int(event.agent_version),
                "entry_id": event.get("entry_id"),
                "hits": _int(event.get("hits")),
                "misses": _int(event.get("misses")),
            }
        )

    clusters: dict[int | None, dict[str, Any]] = {}
    for event in events(conn, kind="drift_detected", agent_id=agent_id):
        version = _int(event.agent_version)
        cluster = clusters.setdefault(
            version,
            {
                "kind": "drift_cluster",
                "ts": event.ts,
                "version": version,
                "count": 0,
                "count_by_kind": {},
            },
        )
        cluster["count"] += 1
        drift_kind = str(event.get("kind") or "unknown")
        cluster["count_by_kind"][drift_kind] = (
            cluster["count_by_kind"].get(drift_kind, 0) + 1
        )
    out.extend(clusters.values())

    out.sort(key=lambda m: (m.get("ts") or "", str(m.get("kind"))))
    return out


# --------------------------------------------------------------------------
# graduation and saturation (PLAN_ADDENDUM.md sec J)
# --------------------------------------------------------------------------


def graduated_count(conn: sqlite3.Connection, agent_id: str) -> int:
    """Distinct tasks ever marked ``task_graduated`` for this agent.

    A task graduates the first version it becomes stably passing; this counts
    each task once even if a later regression and re-fix graduates it again.
    """
    seen: set[str] = set()
    for event in events(conn, kind="task_graduated", agent_id=agent_id):
        case_id = event.get("case_id")
        if case_id is not None:
            seen.add(str(case_id))
    return len(seen)


def saturated(conn: sqlite3.Connection, agent_id: str) -> bool:
    """True iff train pass@1 >= 0.95 for the last two consecutive train runs.

    PLAN_ADDENDUM.md sec J: "capability suite saturated -- add harder tasks".
    """
    train_versions = sorted(
        {v for v, s in _finished_version_splits(conn, agent_id) if s == "train"}
    )
    if len(train_versions) < SATURATION_WINDOW:
        return False
    recent = train_versions[-SATURATION_WINDOW:]
    return all(
        (mean := pass_at_1(conn, agent_id, v, "train")["mean"]) is not None
        and mean >= SATURATION_THRESHOLD
        for v in recent
    )


def zero_pass_tasks(conn: sqlite3.Connection, agent_id: str) -> list[str]:
    """Tasks stuck at 0% across the last ``ZERO_PASS_WINDOW`` train runs.

    PLAN_ADDENDUM.md sec J: a task at 0% after 3 versions is usually a broken
    task, not an incapable agent. Empty until at least that many train runs
    exist, so a young agent is never flagged prematurely.
    """
    train_versions = sorted(
        {v for v, s in _finished_version_splits(conn, agent_id) if s == "train"}
    )
    if len(train_versions) < ZERO_PASS_WINDOW:
        return []
    recent = train_versions[-ZERO_PASS_WINDOW:]

    zero_sets: list[set[str]] = []
    for version in recent:
        run = latest_run(conn, agent_id, version, "train")
        if run is None:
            return []
        by_task = _results_by_task(case_results(conn, run.run_id))
        zero_sets.append(
            {
                task_id
                for task_id, rows in by_task.items()
                if rows and not any(bool(e.get("passed")) for e in rows)
            }
        )

    flagged = zero_sets[0]
    for s in zero_sets[1:]:
        flagged &= s
    return sorted(flagged)


# --------------------------------------------------------------------------
# memory (PLAN_ADDENDUM.md sec E)
# --------------------------------------------------------------------------


def _injected_ids(value: Any) -> list[str]:
    """Normalise ``rules_injected`` -- ids, or objects carrying an id."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for entry in value:
        if isinstance(entry, dict):
            entry_id = entry.get("id") or entry.get("entry_id") or entry.get("rule_id")
            if entry_id is not None:
                out.append(str(entry_id))
        elif entry is not None:
            out.append(str(entry))
    return out


def rule_stats(conn: sqlite3.Connection, agent_id: str) -> dict[str, dict[str, int]]:
    """``{entry_id: {hits, misses, uses}}`` from ``case_result`` rows.

    A hit is a task execution that passed with the rule injected, a miss one
    that failed. Both come from the grader via the runtime -- never from the
    agent's own assessment (PLAN_ADDENDUM.md sec 0).
    """
    stats: dict[str, dict[str, int]] = {}
    for event in events(conn, kind="case_result", agent_id=agent_id):
        passed = bool(event.get("passed"))
        for entry_id in _injected_ids(event.get("rules_injected")):
            entry = stats.setdefault(entry_id, {"hits": 0, "misses": 0, "uses": 0})
            entry["hits" if passed else "misses"] += 1
            entry["uses"] += 1
    return stats


def _agent_versions(conn: sqlite3.Connection, agent_id: str) -> list[int]:
    """Every version 0..max seen for this agent, contiguous, for charting."""
    versions = {
        v
        for v in (_int(e.agent_version) for e in events(conn, agent_id=agent_id))
        if v is not None
    }
    for event in events(conn, kind=("fix_proposed", "fix_accepted"), agent_id=agent_id):
        to_version = _int(event.get("to_version"))
        if to_version is not None:
            versions.add(to_version)
    row = agent_row(conn, agent_id)
    if row and _int(row.get("current_version")) is not None:
        versions.add(_int(row["current_version"]))
    if not versions:
        return []
    return list(range(max(versions) + 1))


def _memory_version(event: Event) -> int | None:
    version = _int(event.get("version"))
    return version if version is not None else _int(event.agent_version)


def memory_by_version(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None
) -> list[dict[str, Any]]:
    """``[{version, rules, tool_notes, mean_confidence, demotions}]``.

    ``rules`` is the number of rules *active* at that version (cumulative
    ``memory_written(kind=rule)`` minus cumulative ``memory_demoted``);
    ``tool_notes`` is cumulative; ``demotions`` counts demotions at that
    version alone, so the chart can mark them. ``mean_confidence`` is read
    from ``agents/<id>/v<N>/memory/rules.jsonl`` and is ``None`` when that
    snapshot is not on disk or carries no confidences.
    """
    written = events(conn, kind="memory_written", agent_id=agent_id)
    demoted = events(conn, kind="memory_demoted", agent_id=agent_id)

    rules_at: dict[int, int] = {}
    notes_at: dict[int, int] = {}
    for event in written:
        version = _memory_version(event)
        if version is None:
            continue
        entry_kind = str(event.get("kind") or "")
        if entry_kind == "rule":
            rules_at[version] = rules_at.get(version, 0) + 1
        elif entry_kind == "tool_note":
            notes_at[version] = notes_at.get(version, 0) + 1

    demotions_at: dict[int, int] = {}
    for event in demoted:
        version = _memory_version(event)
        if version is None:
            continue
        demotions_at[version] = demotions_at.get(version, 0) + 1

    out: list[dict[str, Any]] = []
    rules_total = 0
    notes_total = 0
    demoted_total = 0
    for version in _agent_versions(conn, agent_id):
        rules_total += rules_at.get(version, 0)
        notes_total += notes_at.get(version, 0)
        demotions = demotions_at.get(version, 0)
        demoted_total += demotions
        out.append(
            {
                "version": version,
                "rules": rules_total - demoted_total,
                "rules_written": rules_total,
                "tool_notes": notes_total,
                "mean_confidence": _mean_confidence(agent_id, version, root),
                "demotions": demotions,
            }
        )
    return out


def _mean_confidence(
    agent_id: str, version: int, root: str | Path | None
) -> float | None:
    path = (
        repo_root(root) / "agents" / agent_id / f"v{version}" / "memory" / "rules.jsonl"
    )
    confidences = [
        c
        for c in (_num(r.get("confidence")) for r in _read_jsonl(path))
        if c is not None
    ]
    return _mean(confidences)


# --------------------------------------------------------------------------
# tool usage (PLAN_ADDENDUM.md sec K)
# --------------------------------------------------------------------------


def _normalized_args_key(args: Any) -> str:
    """A stable, order-independent key for tool-call args."""
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except TypeError:
        return str(args)


def _transcript_tool_calls(
    transcript_path: str | None, root: str | Path | None
) -> list[dict[str, Any]] | None:
    """The harness-recorded ``tool_calls`` list from a transcript, or None if absent.

    Expected shape per call: ``{tool, args, error: bool, tokens_in: int}``. This
    is the interface W1 needs from W2's transcript writer; until that lands,
    callers fall back to the coarser ``case_result`` counters.
    """
    data = _read_json(_resolve(transcript_path, root))
    if not isinstance(data, dict):
        return None
    calls = data.get("tool_calls")
    return calls if isinstance(calls, list) else None


def _execution_tool_stats(event: Event, root: str | Path | None) -> dict[str, float]:
    """Tool stats for one task execution (one (task, trial) pair)."""
    calls = _transcript_tool_calls(event.get("transcript_path"), root)
    if calls is not None:
        seen: set[str] = set()
        redundant = 0
        errors = 0
        tokens = 0.0
        for call in calls:
            if not isinstance(call, dict):
                continue
            key = f"{call.get('tool')}::{_normalized_args_key(call.get('args'))}"
            if key in seen:
                redundant += 1
            seen.add(key)
            if call.get("error"):
                errors += 1
            tokens += _num(call.get("tokens_in")) or 0.0
        return {
            "calls": float(len(calls)),
            "errors": float(errors),
            "redundant": float(redundant),
            "tool_tokens": tokens,
            "latency_ms": _num(event.get("latency_ms")) or 0.0,
        }

    # No transcript detail on disk: fall back to the coarser case_result
    # counters. Redundant calls and tool-response tokens cannot be recovered
    # from these alone, so they are honestly reported as unknown (None), not 0.
    return {
        "calls": _num(event.get("tool_calls")) or 0.0,
        "errors": _num(event.get("tool_errors")) or 0.0,
        "redundant": None,
        "tool_tokens": None,
        "latency_ms": _num(event.get("latency_ms")) or 0.0,
    }


def tool_call_stats(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int,
    split: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Per-task and aggregate tool usage for the latest run of ``(agent, version, split)``.

    ``tasks`` maps each task id to its mean stats across trials; ``aggregate``
    is the mean over every task execution (task, trial). Redundant calls are
    "same tool, identical normalized args, within one trial" (PLAN_ADDENDUM.md
    sec K), computed from the transcript's recorded tool-call list when present.
    """
    run = latest_run(conn, agent_id, version, split)
    empty = {
        "calls": None,
        "errors": None,
        "redundant": None,
        "tool_tokens": None,
        "latency_ms": None,
    }
    if run is None:
        return {"tasks": {}, "aggregate": dict(empty)}

    results = case_results(conn, run.run_id)
    if not results:
        return {"tasks": {}, "aggregate": dict(empty)}

    per_execution = [_execution_tool_stats(e, root) for e in results]

    def field_mean(key: str, rows: Sequence[dict[str, float]]) -> float | None:
        values = [r[key] for r in rows if r.get(key) is not None]
        return _mean(values)

    by_task: dict[str, list[dict[str, float]]] = {}
    for event, stats in zip(results, per_execution, strict=True):
        case_id = event.get("case_id")
        if case_id is None:
            continue
        by_task.setdefault(str(case_id), []).append(stats)

    tasks = {
        task_id: {key: field_mean(key, rows) for key in empty}
        for task_id, rows in by_task.items()
    }
    aggregate = {key: field_mean(key, per_execution) for key in empty}
    return {"tasks": tasks, "aggregate": aggregate}


def tool_stats_by_version(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None
) -> list[dict[str, Any]]:
    """``[{version, split, calls, errors, redundant, tool_tokens, latency_ms}]``.

    One row per (version, split) with a finished run, aggregated per task.
    Expected to fall as memory grows (judge question 4).
    """
    out: list[dict[str, Any]] = []
    for version, split in _finished_version_splits(conn, agent_id):
        stats = tool_call_stats(conn, agent_id, version, split, root)
        if not stats["tasks"]:
            continue
        out.append({"version": version, "split": split, **stats["aggregate"]})
    return out


# --------------------------------------------------------------------------
# fix cards
# --------------------------------------------------------------------------


def _failing_group(proposal: Event | None) -> dict[str, Any]:
    group = proposal.get("failing_group") if proposal else None
    if not isinstance(group, dict):
        group = {}
    case_ids = group.get("case_ids")
    return {
        "signature": group.get("signature"),
        "tag": group.get("tag"),
        "count": _int(group.get("count")),
        "case_ids": [str(c) for c in case_ids]
        if isinstance(case_ids, (list, tuple))
        else [],
    }


def fix_cards(conn: sqlite3.Connection, agent_id: str) -> list[dict[str, Any]]:
    """``FixCard`` list per ``contracts/api.md`` / PLAN_ADDENDUM.md sec A, newest first.

    One card per ``fix_proposed``, joined to its ``fix_accepted`` /
    ``fix_rejected`` by ``to_version``. A proposal with no outcome yet gets
    ``status = "proposed"`` rather than being dropped. ``memory`` fixes carry
    ``memory_entries`` (the ``memory_written`` payloads for that version) so
    the card can show the entries instead of a text diff.
    """
    outcomes: dict[int, Event] = {}
    for event in events(conn, kind=("fix_accepted", "fix_rejected"), agent_id=agent_id):
        to_version = _int(event.get("to_version"))
        if to_version is not None:
            outcomes[to_version] = event

    memory_by_v: dict[int, list[dict[str, Any]]] = {}
    for event in events(conn, kind="memory_written", agent_id=agent_id):
        version = _memory_version(event)
        if version is not None:
            memory_by_v.setdefault(version, []).append(dict(event.payload))

    cards: list[tuple[int, dict[str, Any]]] = []
    for proposal in events(conn, kind="fix_proposed", agent_id=agent_id):
        to_version = _int(proposal.get("to_version"))
        if to_version is None:
            continue
        from_version = _int(proposal.get("from_version"))
        outcome = outcomes.get(to_version)
        status = (
            "accepted"
            if outcome is not None and outcome.kind == "fix_accepted"
            else "rejected"
            if outcome is not None
            else "proposed"
        )
        lever = _lever_of(proposal, outcome)

        before, after = _card_numbers(conn, agent_id, from_version, outcome, status)

        files_touched = proposal.get("files_touched")
        regressed = outcome.get("regressed_case_ids") if status == "rejected" else None

        card: dict[str, Any] = {
            "to_version": to_version,
            "from_version": from_version,
            "lever": lever,
            "status": status,
            "failing_group": _failing_group(proposal),
            "hypothesis": proposal.get("hypothesis"),
            "diagnosis": proposal.get("diagnosis"),
            "metric_signal": proposal.get("metric_signal"),
            "diff_summary": proposal.get("diff_summary"),
            "files_touched": list(files_touched)
            if isinstance(files_touched, (list, tuple))
            else [],
            "diff_url": f"/agents/{agent_id}/fixes/{to_version}/diff",
            "before": before,
            "after": after,
            "regressed_case_ids": [str(c) for c in regressed]
            if isinstance(regressed, (list, tuple))
            else [],
            "ts": proposal.ts,
        }
        if lever == "memory":
            card["memory_entries"] = memory_by_v.get(to_version, [])
        cards.append((proposal.id, card))

    cards.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in cards]


def _card_numbers(
    conn: sqlite3.Connection,
    agent_id: str,
    from_version: int | None,
    outcome: Event | None,
    status: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(before, after)`` blocks of a fix card, per PLAN_ADDENDUM.md sec A.

    Accepted fixes carry their own before/after numbers in the ``fix_accepted``
    payload (scalar pass@1/pass^k, not mean+-std -- the ledger already recorded
    the mean at gate time). Rejected and still-proposed attempts only record
    the candidate's pass@1, so ``before`` is derived from the ledger at
    ``from_version``.
    """
    empty_before = {
        "pass_at_1": None,
        "pass_pow_k": None,
        "group_pass": None,
        "cost_per_run": None,
        "tool_calls_per_task": None,
    }
    empty_after = {
        "pass_at_1": None,
        "pass_pow_k": None,
        "group_pass": None,
        "holdout_pass_at_1": None,
        "holdout_pass_pow_k": None,
        "cost_per_run": None,
        "tool_calls_per_task": None,
    }

    if status == "accepted" and outcome is not None:
        return (
            {
                "pass_at_1": _num(outcome.get("pass_at_1_before")),
                "pass_pow_k": _num(outcome.get("pass_pow_k_before")),
                "group_pass": _num(outcome.get("group_pass_before")),
                "cost_per_run": _num(outcome.get("cost_per_run_before")),
                "tool_calls_per_task": _num(outcome.get("tool_calls_per_task_before")),
            },
            {
                "pass_at_1": _num(outcome.get("pass_at_1_after")),
                "pass_pow_k": _num(outcome.get("pass_pow_k_after")),
                "group_pass": _num(outcome.get("group_pass_after")),
                "holdout_pass_at_1": _num(outcome.get("holdout_pass_at_1_after")),
                "holdout_pass_pow_k": _num(outcome.get("holdout_pass_pow_k_after")),
                "cost_per_run": _num(outcome.get("cost_per_run_after")),
                "tool_calls_per_task": _num(outcome.get("tool_calls_per_task_after")),
            },
        )

    before = dict(empty_before)
    if from_version is not None:
        before["pass_at_1"] = pass_at_1(conn, agent_id, from_version, "train")["mean"]
        before["pass_pow_k"] = pass_pow_k(conn, agent_id, from_version, "train")["mean"]
        before["cost_per_run"] = cost_per_run(conn, agent_id, from_version, "train")
        before["tool_calls_per_task"] = tool_call_stats(
            conn, agent_id, from_version, "train"
        )["aggregate"]["calls"]

    after = dict(empty_after)
    if outcome is not None:
        after["pass_at_1"] = _num(outcome.get("candidate_pass_at_1"))
    return before, after


def fix_diff(
    conn: sqlite3.Connection,
    agent_id: str,
    to_version: int,
    root: str | Path | None = None,
) -> str | None:
    """The unified diff on disk for a fix, or None when there is no file."""
    proposal = _proposals_by_version(conn, agent_id).get(int(to_version))
    if proposal is None:
        return None
    path = _resolve(proposal.get("diff_path"), root)
    if path is None or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------
# output comparison (PLAN_ADDENDUM.md sec G)
# --------------------------------------------------------------------------


def _final_output(transcript_path: str | None, root: str | Path | None) -> Any:
    """``final_output`` from a transcript on disk (``contracts/transcript.py``)."""
    data = _read_json(_resolve(transcript_path, root))
    if not isinstance(data, dict):
        return None
    for key in ("final_output", "output", "actual"):
        if key in data:
            return data[key]
    return None


def _compare_side(
    conn: sqlite3.Connection,
    agent_id: str,
    version: int | None,
    case_id: str,
    root: str | Path | None,
) -> dict[str, Any] | None:
    if version is None:
        return None
    candidates = [
        e
        for e in events(
            conn, kind="case_result", agent_id=agent_id, agent_version=version
        )
        if str(e.get("case_id")) == str(case_id)
    ]
    if not candidates:
        return None
    trial_zero = [e for e in candidates if (e.trial() or 0) == 0]
    pool = trial_zero or candidates
    event = max(pool, key=lambda e: e.id)

    tokens_in = _num(event.get("tokens_in")) or 0.0
    tokens_out = _num(event.get("tokens_out")) or 0.0
    return {
        "version": version,
        "trial": event.trial() or 0,
        "output": _final_output(event.get("transcript_path"), root),
        "passed": bool(event.get("passed")),
        "score": _num(event.get("score")),
        "rules_injected": _injected_ids(event.get("rules_injected")),
        "tool_calls": _int(event.get("tool_calls")),
        "tokens": int(tokens_in + tokens_out),
        "transcript_path": event.get("transcript_path"),
    }


def _expected_output(
    conn: sqlite3.Connection, agent_id: str, case_id: str, root: str | Path | None
) -> Any:
    row = agent_row(conn, agent_id)
    evaluator_id = row.get("evaluator_id") if row else None
    if not evaluator_id:
        return None
    path = repo_root(root) / "evaluators" / str(evaluator_id) / "cases.jsonl"
    for record in _read_jsonl(path):
        if str(record.get("id")) == str(case_id):
            return record.get("expected")
    return None


def compare(
    conn: sqlite3.Connection,
    agent_id: str,
    case_id: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """One task's output at v0 vs the current version, with what was injected.

    ``{expected, v0, current}``; a side with no recorded result is ``None``.
    The outputs are read from the transcripts the harness wrote, not from
    anything the agent said about itself.
    """
    row = agent_row(conn, agent_id)
    current_version = _int(row.get("current_version")) if row else None
    return {
        "agent_id": agent_id,
        "case_id": case_id,
        "current_version": current_version,
        "expected": _expected_output(conn, agent_id, case_id, root),
        "v0": _compare_side(conn, agent_id, 0, case_id, root),
        "current": _compare_side(conn, agent_id, current_version, case_id, root),
    }


# --------------------------------------------------------------------------
# assembled payloads for the API
# --------------------------------------------------------------------------


def _latest_trials(conn: sqlite3.Connection, agent_id: str) -> int | None:
    finished = runs(conn, agent_id)
    for run in reversed(finished):
        trials = _int(run.trials)
        if trials is not None:
            return trials
    return None


def insights(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None
) -> dict[str, Any]:
    """The full ``GET /insights/{agent_id}`` payload (PLAN_ADDENDUM.md sec A)."""
    row = agent_row(conn, agent_id)
    series = series_by_version(conn, agent_id)
    return {
        "agent_id": agent_id,
        "domain": row.get("domain") if row else None,
        "current_version": _int(row.get("current_version")) if row else None,
        "trials": _latest_trials(conn, agent_id),
        **series,
        "fixes_by_lever": fixes_by_lever(conn, agent_id),
        "regressions_caught": regressions_caught(conn, agent_id),
        "issues": issue_stats(conn, agent_id),
        "lessons_count": lessons_count(conn),
        "drift": drift_stats(conn, agent_id),
        "markers": markers(conn, agent_id),
        "memory_by_version": memory_by_version(conn, agent_id, root),
        "tool_stats_by_version": tool_stats_by_version(conn, agent_id, root),
        "graduated_count": graduated_count(conn, agent_id),
        "saturated": saturated(conn, agent_id),
        "flagged_tasks": zero_pass_tasks(conn, agent_id),
        "rule_stats": rule_stats(conn, agent_id),
    }


def insights_compare(
    conn: sqlite3.Connection, root: str | Path | None = None
) -> dict[str, Any]:
    """``GET /insights/compare``: per-domain series for every agent + ablation.

    ``ablation`` is ``reports/ablation.json`` verbatim when W8 has written it,
    otherwise ``None`` -- never a placeholder.
    """
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for row in agent_rows(conn):
        agent_id = row["agent_id"]
        domain = row.get("domain") or "unknown"
        by_domain.setdefault(domain, []).append(
            {
                "agent_id": agent_id,
                "goal": row.get("goal"),
                "domain": domain,
                "current_version": _int(row.get("current_version")),
                **series_by_version(conn, agent_id),
            }
        )
    return {
        "by_domain": by_domain,
        "ablation": _read_json(repo_root(root) / "reports" / "ablation.json"),
    }
