"""`improve`: the diagnose -> patch -> gate loop (PLAN_ADDENDUM.md section E;
`contracts/api.md`'s `improver.improve` signature).

One call to `improve` makes **at most one accepted version bump**: it
diagnoses the current version's train failures once, then tries diagnoses in
ranked order -- preferring a different lever after each rejection, per
section D -- until one is accepted or `max_attempts` is exhausted. This is
why the acceptance criterion talks about "5 improve iterations": each
iteration is one call to `improve`, made against whatever the current
version is by then. Re-diagnosing the *same* stale failure list after an
accept would be analyzing a version that no longer exists.

If there is no train run recorded yet for the current version, `improve`
runs one first (`trials=EVAL_TRIALS`) -- `diagnose` and `gate` both need a
baseline to read.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.architect.llm_client import CompleteFn
from backend.improver.diagnose import MAX_GROUPS, Diagnosis, diagnose
from backend.improver.gate import RunEvalFn, gate
from backend.improver.grouping import TRAIN_SPLIT, group_train_failures, resolve_evaluator_path
from backend.improver.patch import PatchError, patch
from backend.improver.reflect import Proposal, reflect
from backend.ledger.query import agent_row, events, latest_run
from backend.runtime import neatlogs

__all__ = ["AttemptOutcome", "ImproveResult", "improve"]


@dataclass
class AttemptOutcome:
    attempt: int
    from_version: int
    candidate_version: int
    lever: str
    failing_group_signature: str
    accepted: bool
    reason: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "from_version": self.from_version,
            "candidate_version": self.candidate_version,
            "lever": self.lever,
            "failing_group_signature": self.failing_group_signature,
            "accepted": self.accepted,
            "reason": self.reason,
        }


@dataclass
class ImproveResult:
    agent_id: str
    starting_version: int
    current_version: int
    attempts: list[AttemptOutcome] = field(default_factory=list)
    issue_id: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "starting_version": self.starting_version,
            "current_version": self.current_version,
            "improved": self.current_version != self.starting_version,
            "attempts": [a.payload() for a in self.attempts],
            "issue_id": self.issue_id,
        }


def _issue_case_ids(conn: sqlite3.Connection, issue_id: str) -> set[str]:
    return {
        str(e.get("case_id"))
        for e in events(conn, kind="issue_linked_case")
        if e.get("issue_id") == issue_id
    }


def _order_diagnoses(diagnoses: list[Diagnosis], priority_case_ids: set[str]) -> list[Diagnosis]:
    if not priority_case_ids:
        return list(diagnoses)
    prioritized = [d for d in diagnoses if priority_case_ids & set(d.failing_group.case_ids)]
    prioritized_ids = {id(d) for d in prioritized}
    rest = [d for d in diagnoses if id(d) not in prioritized_ids]
    return prioritized + rest


def _next_diagnosis(remaining: list[Diagnosis], avoid_lever: str | None) -> Diagnosis | None:
    if not remaining:
        return None
    if avoid_lever is not None:
        for i, d in enumerate(remaining):
            if d.lever != avoid_lever:
                return remaining.pop(i)
    return remaining.pop(0)


def _improve(
    agent_id: str,
    max_attempts: int = 3,
    issue_id: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    agents_dir: str | Path | None = None,
    evaluators_dir: str | Path | None = None,
    runs_dir: str | Path | None = None,
    root: str | Path = ".",
    trials: int | None = None,
    model: str | None = None,
    complete: CompleteFn | None = None,
    emit: Any | None = None,
    read_events: Any | None = None,
    run_eval: RunEvalFn | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ImproveResult:
    """Diagnose the current version's failures, then try fixes until one is
    accepted or `max_attempts` is exhausted."""
    from backend.ledger.emit import emit as default_emit_fn
    from backend.runtime.evaluation import run_eval as default_run_eval

    emit = emit or default_emit_fn
    run_eval = run_eval or default_run_eval

    owns_conn = conn is None
    if conn is None:
        from backend.db import init_db

        conn = init_db(db)

    run_kwargs: dict[str, Any] = {}
    if agents_dir is not None:
        run_kwargs["agents_dir"] = agents_dir
    if evaluators_dir is not None:
        run_kwargs["evaluators_dir"] = evaluators_dir
    if runs_dir is not None:
        run_kwargs["runs_dir"] = runs_dir
    if emit is not default_emit_fn:
        run_kwargs["emit"] = emit
    if read_events is not None:
        run_kwargs["read_events"] = read_events
    if complete is not None:
        run_kwargs["complete"] = complete

    try:
        row = agent_row(conn, agent_id)
        if row is None:
            raise ValueError(f"unknown agent_id {agent_id!r}")
        version = int(row["current_version"])

        if latest_run(conn, agent_id, version, TRAIN_SPLIT) is None:
            run_eval(agent_id, version=version, split=TRAIN_SPLIT, trials=trials, **run_kwargs)

        # Reflection is the FIRST step (section E), not a subroutine of the
        # memory lever. It runs on every top failure group before anything is
        # diagnosed, so the agent's own reading of what went wrong is on the
        # table whichever lever the analyst later picks -- and so a run whose
        # diagnoses all come back `tools`/`prompt` still produces reflection.
        groups = group_train_failures(
            conn, agent_id, version, resolve_evaluator_path(conn, agent_id)
        )[:MAX_GROUPS]
        result = ImproveResult(
            agent_id=agent_id, starting_version=version, current_version=version, issue_id=issue_id
        )
        if not groups:
            return result

        proposals_by_signature: dict[str, list[Proposal]] = {
            group.signature: reflect(
                agent_id, version, group, conn=conn, root=root, model=model, complete=complete
            )
            for group in groups
        }

        diagnoses = diagnose(
            agent_id,
            version,
            conn=conn,
            root=root,
            model=model,
            complete=complete,
            groups=groups,
            reflections=proposals_by_signature,
        )
        if not diagnoses:
            return result

        priority_case_ids = _issue_case_ids(conn, issue_id) if issue_id else set()
        remaining = _order_diagnoses(diagnoses, priority_case_ids)

        avoid_lever: str | None = None
        next_candidate = version + 1
        attempt = 0
        total = max(1, max_attempts)

        while attempt < max_attempts:
            diagnosis = _next_diagnosis(remaining, avoid_lever)
            if diagnosis is None:
                break
            attempt += 1

            this_issue_id = (
                issue_id
                if issue_id and priority_case_ids & set(diagnosis.failing_group.case_ids)
                else None
            )
            with neatlogs.span(
                "task_orchestrator.improve.attempt",
                kind="CHAIN",
                attempt=attempt,
                from_version=version,
                candidate_version=next_candidate,
                lever=(
                    diagnosis.lever if diagnosis.lever in {"memory", "prompt", "tools"} else "other"
                ),
            ):
                try:
                    candidate = patch(
                        agent_id,
                        version,
                        diagnosis,
                        candidate_version=next_candidate,
                        conn=conn,
                        agents_dir=agents_dir or _default_agents_dir(),
                        root=root,
                        model=model,
                        complete=complete,
                        emit=emit,
                        issue_id=this_issue_id,
                        proposals=proposals_by_signature.get(diagnosis.failing_group.signature, []),
                    )
                except PatchError:
                    avoid_lever = diagnosis.lever
                    next_candidate += 1
                    if progress is not None:
                        progress(attempt, total)
                    continue

            accepted = gate(
                agent_id,
                candidate,
                conn=conn,
                trials=trials,
                run_eval=run_eval,
                emit=emit,
                read_events=read_events,
                complete=complete,
                root=root,
                runs_dir=runs_dir,
                agents_dir=agents_dir,
                evaluators_dir=evaluators_dir,
            )
            reason = None
            if not accepted:
                for e in reversed(events(conn, kind="fix_rejected", agent_id=agent_id)):
                    if e.get("to_version") == candidate:
                        reason = e.get("reason")
                        break

            result.attempts.append(
                AttemptOutcome(
                    attempt=attempt,
                    from_version=version,
                    candidate_version=candidate,
                    lever=diagnosis.lever,
                    failing_group_signature=diagnosis.failing_group.signature,
                    accepted=accepted,
                    reason=reason,
                )
            )
            if progress is not None:
                progress(attempt, total)

            if accepted:
                result.current_version = candidate
                break

            avoid_lever = diagnosis.lever
            next_candidate += 1

        return result
    finally:
        if owns_conn:
            conn.close()


def improve(
    agent_id: str,
    max_attempts: int = 3,
    issue_id: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    db: str | Path | None = None,
    agents_dir: str | Path | None = None,
    evaluators_dir: str | Path | None = None,
    runs_dir: str | Path | None = None,
    root: str | Path = ".",
    trials: int | None = None,
    model: str | None = None,
    complete: CompleteFn | None = None,
    emit: Any | None = None,
    read_events: Any | None = None,
    run_eval: RunEvalFn | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ImproveResult:
    """Run the improve workflow without exporting issue text or model content."""
    with neatlogs.workflow_span(
        "task_orchestrator.improve",
        agent_id=neatlogs.safe_identifier(agent_id, "agent"),
        issue_id=neatlogs.safe_identifier(issue_id, "issue") if issue_id else None,
        max_attempts=max_attempts,
        trials=trials,
    ):
        return _improve(
            agent_id,
            max_attempts=max_attempts,
            issue_id=issue_id,
            conn=conn,
            db=db,
            agents_dir=agents_dir,
            evaluators_dir=evaluators_dir,
            runs_dir=runs_dir,
            root=root,
            trials=trials,
            model=model,
            complete=complete,
            emit=emit,
            read_events=read_events,
            run_eval=run_eval,
            progress=progress,
        )


def _default_agents_dir() -> str:
    from backend.runtime.package import DEFAULT_AGENTS_DIR

    return str(DEFAULT_AGENTS_DIR)
