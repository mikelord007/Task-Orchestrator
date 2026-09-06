"""Domain B (`ticket_triage`) playbook ablation (contracts/playbook.md, W8 brief).

Creates the `ticket_triage` agent twice -- once with `use_playbook=False`,
once with `use_playbook=True` -- runs holdout on both v0s at `EVAL_TRIALS`,
and writes `reports/ablation.json`:

    {domain, trials,
     playbook_off: {pass_at_1, pass_pow_k, std},
     playbook_on:  {pass_at_1, pass_pow_k, std},
     applied_lesson_ids: [...],
     agent_ids: {playbook_off, playbook_on}}

This is a demo artifact (contracts/playbook.md "Ablation"): a flat or negative
result is written as-is, never massaged. `GET /insights/compare` reads this
file verbatim if present.

    uv run --project backend python scripts/playbook_ablation.py

Requires `backend.runtime.eval.run_eval` (W2) and a real or FakeLLM-backed
`backend.llm.complete` to be usable end to end; `run_ablation()` below takes
both as injectable arguments so it can be exercised offline in tests.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from backend.architect.generate import generate
from backend.architect.llm_client import CompleteFn
from backend.db import REPO_ROOT, init_db
from backend.ledger import metrics
from backend.ledger.query import events
from backend.settings import eval_trials

DOMAIN = "ticket_triage"
EVALUATOR_ID = "ticket_triage"
GOAL = "Triage inbound support tickets: category, priority, and whether a human must respond."
TOOLS = ["html_to_text", "regex_extract", "date_parse", "json_validate", "number_parse"]
SPLIT = "holdout"
VERSION = 0


class RunEvalFn(Protocol):
    def __call__(self, agent_id: str, version: int, split: str, trials: int) -> Any: ...


def _resolve_run_eval() -> RunEvalFn:
    """Lazy import: W2's runtime eval harness (`backend/runtime/`, PLAN.md 4.5,
    PLAN_ADDENDUM.md §B) is a separate, not-yet-merged workstream. Importing it
    only when actually running the ablation keeps this module importable --
    and its logic testable with a stub -- before that package exists."""
    from backend.runtime.eval import run_eval  # type: ignore[import-not-found]

    return run_eval


def _applied_lesson_ids(conn: sqlite3.Connection, agent_id: str) -> list[str]:
    created = events(conn, kind="agent_created", agent_id=agent_id)
    if not created:
        return []
    applied = created[0].get("applied_lessons") or []
    return [str(lesson_id) for lesson_id in applied]


def _pass_stats(conn: sqlite3.Connection, agent_id: str, split: str) -> dict[str, float | None]:
    pass_1 = metrics.pass_at_1(conn, agent_id, VERSION, split)
    pass_k = metrics.pass_pow_k(conn, agent_id, VERSION, split)
    return {"pass_at_1": pass_1["mean"], "pass_pow_k": pass_k["mean"], "std": pass_1["std"]}


def run_ablation(
    *,
    conn: sqlite3.Connection,
    trials: int,
    agents_root: str | Path,
    evaluators_root: str | Path,
    playbook_path: str | Path,
    run_eval: RunEvalFn | None = None,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Build both v0 agents, run holdout on each, and assemble the report dict.

    Reads pass rates back through `backend.ledger.metrics` rather than
    trusting whatever `run_eval` returns directly: the ledger events it wrote
    are the one shared source of truth every other chart also reads (rule
    §2.8), so this stays correct regardless of `run_eval`'s own return shape.
    """
    run_eval = run_eval or _resolve_run_eval()

    off = generate(
        goal=GOAL,
        domain=DOMAIN,
        tools=TOOLS,
        evaluator_id=EVALUATOR_ID,
        use_playbook=False,
        complete=complete,
        model=model,
        agents_root=agents_root,
        evaluators_root=evaluators_root,
        playbook_path=playbook_path,
        conn=conn,
    )
    on = generate(
        goal=GOAL,
        domain=DOMAIN,
        tools=TOOLS,
        evaluator_id=EVALUATOR_ID,
        use_playbook=True,
        complete=complete,
        model=model,
        agents_root=agents_root,
        evaluators_root=evaluators_root,
        playbook_path=playbook_path,
        conn=conn,
    )

    run_eval(off.agent_id, VERSION, SPLIT, trials)
    run_eval(on.agent_id, VERSION, SPLIT, trials)

    return {
        "domain": DOMAIN,
        "trials": trials,
        "playbook_off": _pass_stats(conn, off.agent_id, SPLIT),
        "playbook_on": _pass_stats(conn, on.agent_id, SPLIT),
        "applied_lesson_ids": _applied_lesson_ids(conn, on.agent_id),
        "agent_ids": {"playbook_off": off.agent_id, "playbook_on": on.agent_id},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "reports" / "ablation.json"),
        help="Where to write the report (default: reports/ablation.json)",
    )
    args = parser.parse_args(argv)

    conn = init_db()
    try:
        report = run_ablation(
            conn=conn,
            trials=eval_trials(),
            agents_root=REPO_ROOT / "agents",
            evaluators_root=REPO_ROOT / "evaluators",
            playbook_path=REPO_ROOT / "playbook" / "lessons.jsonl",
        )
    finally:
        conn.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
