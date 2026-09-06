"""Gate: the one place a candidate version earns `current_version`
(PLAN_ADDENDUM.md section B).

`gate(agent_id, candidate_version)` runs the candidate's full train set at
`EVAL_TRIALS`, then accepts iff (a) every task in the prior version's stable
pass set is still in the candidate's stable pass set, and (b) the candidate's
`pass@1` is >= the prior version's. Accepting bumps `agents.current_version`
and records one holdout run; rejecting leaves everything but the ledger and
the (already-written-by-`patch`) candidate directory untouched -- the
candidate stays on disk as evidence.

`gate` never looks at the failing group's *content* to decide accept/reject
(that would let a lucky group-local improvement mask a global regression);
it only reads it back from the `fix_proposed` event `patch` wrote, to report
`group_pass_before/after` on the accepted/rejected event.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from backend.improver.grouping import TRAIN_SPLIT
from backend.ledger.metrics import (
    cost_per_run,
    pass_at_1,
    pass_pow_k,
    stable_pass_set,
    tool_call_stats,
)
from backend.ledger.query import case_results, events, latest_run
from contracts.events import RejectReason

__all__ = ["GateResult", "RunEvalFn", "gate"]

HOLDOUT_SPLIT = "holdout"


class RunEvalFn(Protocol):
    def __call__(
        self,
        agent_id: str,
        version: int | None = None,
        split: str = TRAIN_SPLIT,
        trials: int | None = None,
        **kwargs: Any,
    ) -> Any: ...


@dataclass
class GateResult:
    accepted: bool
    candidate_version: int
    pass_at_1_before: float
    pass_at_1_after: float
    reason: str | None = None
    regressed_case_ids: list[str] | None = None


def _rate(pairs: list[tuple[str, bool]], case_ids: set[str]) -> float | None:
    relevant = [passed for case_id, passed in pairs if case_id in case_ids]
    if not relevant:
        return None
    return sum(1 for p in relevant if p) / len(relevant)


def _pairs_from_ledger(conn: sqlite3.Connection, run_id: str) -> list[tuple[str, bool]]:
    return [(str(e.get("case_id")), bool(e.get("passed"))) for e in case_results(conn, run_id)]


def _pairs_from_summary(summary: Any) -> list[tuple[str, bool]]:
    return [(o.case_id, bool(o.passed)) for o in summary.cases]


def _failing_group_case_ids(
    conn: sqlite3.Connection, agent_id: str, candidate_version: int
) -> list[str]:
    for event in reversed(events(conn, kind="fix_proposed", agent_id=agent_id)):
        if event.get("to_version") == candidate_version:
            group = event.get("failing_group") or {}
            case_ids = group.get("case_ids")
            return [str(c) for c in case_ids] if isinstance(case_ids, (list, tuple)) else []
    return []


def _lever_for(conn: sqlite3.Connection, agent_id: str, candidate_version: int) -> str | None:
    for event in reversed(events(conn, kind="fix_proposed", agent_id=agent_id)):
        if event.get("to_version") == candidate_version:
            return event.lever
    return None


def gate(
    agent_id: str,
    candidate_version: int,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    run_eval: RunEvalFn | None = None,
    emit: Any | None = None,
    read_events: Any | None = None,
    complete: Any | None = None,
    trials: int | None = None,
    runs_dir: str | Path | None = None,
    agents_dir: str | Path | None = None,
    evaluators_dir: str | Path | None = None,
    root: str | Path = ".",
) -> bool:
    """Run the candidate's train set, accept or reject, and emit the verdict.

    Returns `True` on accept, `False` on reject. On accept, also runs holdout
    once and bumps `agents.current_version`.
    """
    from backend.ledger.emit import emit as default_emit_fn
    from backend.runtime.evaluation import run_eval as default_run_eval
    from backend.runtime.evaluation import stable_pass_set as runtime_stable_pass_set

    emit = emit or default_emit_fn
    run_eval = run_eval or default_run_eval

    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)

    try:
        prior_version = candidate_version - 1
        lever = _lever_for(conn, agent_id, candidate_version) or "unknown"
        group_case_ids = set(_failing_group_case_ids(conn, agent_id, candidate_version))

        prior_stable = stable_pass_set(conn, agent_id, prior_version)
        prior_pass_stat = pass_at_1(conn, agent_id, prior_version, TRAIN_SPLIT)
        prior_pass_at_1 = prior_pass_stat["mean"] if prior_pass_stat["mean"] is not None else 0.0
        prior_pow_k_stat = pass_pow_k(conn, agent_id, prior_version, TRAIN_SPLIT)
        prior_pow_k = prior_pow_k_stat["mean"] if prior_pow_k_stat["mean"] is not None else 0.0
        prior_run = latest_run(conn, agent_id, prior_version, TRAIN_SPLIT)
        prior_pairs = _pairs_from_ledger(conn, prior_run.run_id) if prior_run else []
        prior_cost = cost_per_run(conn, agent_id, prior_version, TRAIN_SPLIT) or 0.0
        prior_stats = tool_call_stats(conn, agent_id, prior_version, TRAIN_SPLIT, root)
        prior_calls = prior_stats["aggregate"]["calls"] or 0.0

        run_kwargs: dict[str, Any] = {}
        if runs_dir is not None:
            run_kwargs["runs_dir"] = runs_dir
        if agents_dir is not None:
            run_kwargs["agents_dir"] = agents_dir
        if evaluators_dir is not None:
            run_kwargs["evaluators_dir"] = evaluators_dir
        if emit is not default_emit_fn:
            run_kwargs["emit"] = emit
        if read_events is not None:
            run_kwargs["read_events"] = read_events
        if complete is not None:
            run_kwargs["complete"] = complete

        summary = run_eval(
            agent_id, version=candidate_version, split=TRAIN_SPLIT, trials=trials, **run_kwargs
        )
        candidate_pairs = _pairs_from_summary(summary)
        candidate_stable = runtime_stable_pass_set(summary.cases, summary.trials)
        candidate_pass_at_1 = summary.pass_at_1

        no_regression = prior_stable.issubset(candidate_stable)
        accepted = no_regression and candidate_pass_at_1 >= prior_pass_at_1

        if accepted:
            holdout_summary = run_eval(
                agent_id,
                version=candidate_version,
                split=HOLDOUT_SPLIT,
                trials=trials,
                **run_kwargs,
            )
            candidate_calls = (
                sum(o.tool_calls for o in summary.cases) / len(summary.cases)
                if summary.cases
                else 0.0
            )
            emit(
                "fix_accepted",
                agent_id=agent_id,
                agent_version=candidate_version,
                lever=lever,
                to_version=candidate_version,
                pass_at_1_before=prior_pass_at_1,
                pass_at_1_after=candidate_pass_at_1,
                pass_pow_k_before=prior_pow_k,
                pass_pow_k_after=summary.pass_pow_k,
                group_pass_before=_rate(prior_pairs, group_case_ids) or 0.0,
                group_pass_after=_rate(candidate_pairs, group_case_ids) or 0.0,
                holdout_pass_at_1_after=holdout_summary.pass_at_1,
                holdout_pass_pow_k_after=holdout_summary.pass_pow_k,
                cost_per_run_before=prior_cost,
                cost_per_run_after=summary.total_cost_usd,
                tool_calls_per_task_before=prior_calls,
                tool_calls_per_task_after=candidate_calls,
            )
            conn.execute(
                "UPDATE agents SET current_version = ? WHERE agent_id = ?",
                (candidate_version, agent_id),
            )
            conn.commit()
            return True

        regressed = sorted(prior_stable - candidate_stable)
        reason = RejectReason.regression.value if regressed else RejectReason.no_gain.value
        emit(
            "fix_rejected",
            agent_id=agent_id,
            agent_version=candidate_version,
            lever=lever,
            to_version=candidate_version,
            reason=reason,
            regressed_case_ids=regressed,
            candidate_pass_at_1=candidate_pass_at_1,
        )
        return False
    except Exception as exc:  # noqa: BLE001 - a broken candidate is a rejected candidate, not a crashed gate
        try:
            emit(
                "fix_rejected",
                agent_id=agent_id,
                agent_version=candidate_version,
                to_version=candidate_version,
                reason=RejectReason.error.value,
                regressed_case_ids=[],
                candidate_pass_at_1=0.0,
            )
        except Exception:  # noqa: BLE001 - never let error-reporting mask the original error
            pass
        import logging

        logging.getLogger(__name__).warning(
            "gate(%s, v%s) errored, rejecting: %s: %s",
            agent_id,
            candidate_version,
            type(exc).__name__,
            exc,
        )
        return False
    finally:
        if owns_conn:
            conn.close()
