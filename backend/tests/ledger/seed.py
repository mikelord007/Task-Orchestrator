"""A seeded ledger + on-disk artefacts for the metrics tests (and W9's mocks).

The scenario is deliberately small enough that every number in
``backend/tests/ledger/test_metrics.py`` is hand-computed in the test, not
recomputed by the code under test.

Terminology follows PLAN_ADDENDUM.md sec J: a **task** is one evaluator case, a
**trial** is one repeated execution of a task, the **grader** is ``score.py``.
The ``case_result``/``drift_detected`` payload field is canonically ``trial``;
``query.Event.trial()`` also accepts ``repeat`` as an alias for events written
before the rename, but everything this fixture writes uses ``trial``.

What it contains
-----------------
* agent ``agent_demo`` (``github_triage``), versions 0 and 1, ``trials = 3``
* 4 train tasks -- 2 stable passes, 1 flaky (2/3 at v0), 1 that only starts
  passing at v1 -- and 2 holdout tasks
* drift: a budget abort, two loop nudges (one of which recovers), a step-limit
  abort at v1
* one accepted fix (lever ``memory``, 0 -> 1, carrying a ``metric_signal``) and
  one rejected fix (lever ``prompt``, 1 -> 2, rejected for regression), each
  with a diff file on disk
* ``memory_written`` / ``memory_demoted`` events plus the matching
  ``agents/<id>/v<N>/memory/rules.jsonl`` snapshots (rules carry ``demoted``)
* ``rules_injected`` on the v1 case results
* ``task_graduated`` for c1/c2 at v0 and c3 at v1 (the version each first
  became stably passing)
* per-execution tool-call detail on every transcript (redundant calls + tool-
  response tokens at v0, none at v1) so ``tool_call_stats`` has something to
  compute
* one auto issue (open) and one human issue (fixed), two lessons
* a second agent ``agent_b`` (``ticket_triage``) so ``/insights/compare`` has
  more than one domain to group

The demotion of ``r3`` carries the hits/misses this fixture's own case results
produce (1 hit, 2 misses); the "at least 4 uses" threshold is the runtime's
policy (PLAN_ADDENDUM.md sec E), not something the ledger enforces.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# PLAN_ADDENDUM.md sec A / sec E verbatim. Phase 0's ``backend/db.py`` owns the
# real migrations; this mirrors them so the metrics tests can run standalone.
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  kind          TEXT NOT NULL,
  agent_id      TEXT,
  agent_version INTEGER,
  run_id        TEXT,
  lever         TEXT,
  payload       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  agent_id        TEXT PRIMARY KEY,
  goal            TEXT,
  domain          TEXT,
  evaluator_id    TEXT,
  current_version INTEGER,
  created_ts      TEXT
);
CREATE TABLE IF NOT EXISTS issues (
  id                TEXT PRIMARY KEY,
  agent_id          TEXT,
  title             TEXT,
  body              TEXT,
  screenshot_path   TEXT,
  source            TEXT,
  status            TEXT,
  failure_signature TEXT,
  created_ts        TEXT,
  fixed_version     INTEGER
);
"""

AGENT_ID = "agent_demo"
AGENT_B_ID = "agent_b"
EVALUATOR_ID = "github_triage"
TRIALS = 3

TRAIN_TASKS = ["c1", "c2", "c3", "c4"]
HOLDOUT_TASKS = ["h1", "h2"]

# task_id -> passed per trial index.
V0_TRAIN = {
    "c1": [True, True, True],
    "c2": [True, True, True],
    "c3": [True, False, True],  # flaky: never in the stable set
    "c4": [False, False, False],
}
V1_TRAIN = {
    "c1": [True, True, True],
    "c2": [True, True, True],
    "c3": [True, True, True],
    "c4": [True, False, False],
}
V0_HOLDOUT = {"h1": [True, True, True], "h2": [False, False, False]}
V1_HOLDOUT = {"h1": [True, True, True], "h2": [True, False, True]}

# Rules the runtime injected, per version and task.
V1_RULES = {"c1": ["r1", "r2"], "c2": ["r1", "r2"], "c3": ["r1", "r2"], "c4": ["r3"]}
V1_HOLDOUT_RULES = {"h1": ["r1"], "h2": ["r1"]}

DRIFT_TOKEN_BUDGET = 20_000


class _Clock:
    """Monotonic ISO8601 timestamps so event order and ``since`` are testable."""

    def __init__(self, start: str = "2026-09-06T10:00:00") -> None:
        self._base = start
        self._tick = 0

    def next(self) -> str:
        seconds = self._tick
        self._tick += 1
        hh = 10 + seconds // 3600
        mm = (seconds % 3600) // 60
        ss = seconds % 60
        return f"2026-09-06T{hh:02d}:{mm:02d}:{ss:02d}Z"


@dataclass
class SeededLedger:
    """Handles the tests need: ids, run ids, and the filesystem root."""

    conn: sqlite3.Connection
    root: Path
    agent_id: str = AGENT_ID
    agent_b_id: str = AGENT_B_ID
    evaluator_id: str = EVALUATOR_ID
    trials: int = TRIALS
    run_ids: dict[str, str] = field(default_factory=dict)


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the tables the ledger reads. Replaced by ``backend.db`` migrations."""
    conn.executescript(SCHEMA)
    conn.commit()


def _insert(
    conn: sqlite3.Connection,
    kind: str,
    ts: str,
    /,
    *,
    agent_id: str | None = None,
    agent_version: int | None = None,
    run_id: str | None = None,
    lever: str | None = None,
    **payload: Any,
) -> None:
    """Append one event.

    NOTE: swap this body for ``backend.ledger.emit.emit`` once Phase 0 is on
    ``main`` so the fixture's payloads are validated against
    ``contracts/events.py`` like every other writer's.
    """
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, lever, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, kind, agent_id, agent_version, run_id, lever, json.dumps(payload)),
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _final_output(case_id: str, passed: bool) -> dict[str, Any]:
    """What the harness recorded the agent answering. c4 is the demo task."""
    if case_id == "c4":
        if passed:
            return {"labels": ["bug", "windows"], "component": "pty"}
        return {"labels": ["bug"], "component": "core"}
    if passed:
        return {"labels": ["bug"], "component": "core"}
    return {"labels": [], "component": None}


def _tool_call_records(
    count: int, errors: int, redundant: int, tokens_in: int
) -> list[dict[str, Any]]:
    """Synthetic per-call detail: ``redundant`` calls repeat the first call's args.

    Matches the shape :func:`backend.ledger.metrics._transcript_tool_calls`
    expects: ``{tool, args, error, tokens_in}`` per call.
    """
    unique = max(count - redundant, 0)
    calls = [
        {
            "tool": "list_issues",
            "args": {"page": i},
            "error": False,
            "tokens_in": tokens_in,
        }
        for i in range(unique)
    ]
    calls += [
        {
            "tool": "list_issues",
            "args": {"page": 0},
            "error": False,
            "tokens_in": tokens_in,
        }
        for _ in range(count - unique)
    ]
    for i in range(errors):
        calls[-(i + 1)]["error"] = True
    return calls


def _emit_run(
    conn: sqlite3.Connection,
    clock: _Clock,
    root: Path,
    *,
    agent_id: str,
    version: int,
    split: str,
    run_id: str,
    patterns: dict[str, list[bool]],
    cost_usd: float,
    latency_base: float,
    latency_step: float,
    tokens_in: int,
    tokens_out: int,
    tool_calls: int,
    tool_errors: int,
    redundant_tool_calls: int = 0,
    tool_tokens_per_call: int = 0,
    rules: dict[str, list[str]] | None = None,
    drift: dict[tuple[str, int], dict[str, Any]] | None = None,
) -> None:
    """Emit run_started, one case_result per (task, trial), and run_finished."""
    task_ids = list(patterns)
    trials = len(next(iter(patterns.values())))
    drift = drift or {}
    rules = rules or {}

    _insert(
        conn,
        "run_started",
        clock.next(),
        agent_id=agent_id,
        agent_version=version,
        run_id=run_id,
        split=split,
        case_count=len(task_ids),
        trials=trials,
    )

    index = 0
    drift_ids: dict[tuple[str, int], int] = {}
    total_cost = 0.0
    latencies: list[float] = []
    for trial in range(trials):
        for case_id in task_ids:
            latency = latency_base + latency_step * index
            index += 1
            passed = patterns[case_id][trial]
            spec = drift.get((case_id, trial))

            if spec is not None:
                _insert(
                    conn,
                    "drift_detected",
                    clock.next(),
                    agent_id=agent_id,
                    agent_version=version,
                    run_id=run_id,
                    case_id=case_id,
                    trial=trial,
                    step=spec.get("step", 7),
                    kind=spec["kind"],
                    evidence=spec.get("evidence", "observed by the harness"),
                    action=spec["action"],
                    tokens_at_detection=spec["tokens_at_detection"],
                )
                drift_ids[(case_id, trial)] = int(
                    conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                )

            transcript_rel = f"runs/{run_id}/{case_id}.t{trial}.json"
            _write_json(
                root / transcript_rel,
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "trial": trial,
                    "agent_id": agent_id,
                    "version": version,
                    "tool_calls": _tool_call_records(
                        tool_calls,
                        tool_errors,
                        redundant_tool_calls,
                        tool_tokens_per_call,
                    ),
                    "final_output": _final_output(case_id, passed),
                    "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                },
            )

            payload: dict[str, Any] = {
                "case_id": case_id,
                "trial": trial,
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
                "latency_ms": latency,
                "steps": 5,
                "transcript_path": transcript_rel,
                "tool_calls": tool_calls,
                "tool_errors": tool_errors,
                "rules_injected": rules.get(case_id, []),
            }
            if spec is not None and spec["action"] == "abort":
                payload["failure_signature"] = f"drift:{spec['kind']}"
                payload["drift_event_id"] = drift_ids[(case_id, trial)]
            elif not passed:
                payload["failure_signature"] = "wrong_component"

            _insert(
                conn,
                "case_result",
                clock.next(),
                agent_id=agent_id,
                agent_version=version,
                run_id=run_id,
                **payload,
            )
            total_cost += cost_usd
            latencies.append(latency)

    per_task = [sum(flags) / len(flags) for flags in patterns.values()]
    per_trial = [
        sum(patterns[c][t] for c in task_ids) / len(task_ids) for t in range(trials)
    ]
    stable = sum(1 for flags in patterns.values() if all(flags))
    pass_at_1_mean = sum(per_task) / len(per_task)
    pass_pow_k_mean = stable / len(task_ids)
    variance = sum((v - sum(per_trial) / len(per_trial)) ** 2 for v in per_trial) / len(
        per_trial
    )
    aborts = [s for s in drift.values() if s["action"] == "abort"]

    _insert(
        conn,
        "run_finished",
        clock.next(),
        agent_id=agent_id,
        agent_version=version,
        run_id=run_id,
        split=split,
        trials=trials,
        pass_at_1=pass_at_1_mean,
        pass_pow_k=pass_pow_k_mean,
        pass_rate_std=variance**0.5,
        pass_rate_min=min(per_trial),
        pass_rate_max=max(per_trial),
        total_cost_usd=total_cost,
        p50_latency_ms=sorted(latencies)[len(latencies) // 2],
        p95_latency_ms=max(latencies),
        drift_count=len(drift),
        tokens_saved_by_drift=sum(
            max(0, DRIFT_TOKEN_BUDGET - s["tokens_at_detection"]) for s in aborts
        ),
    )

    if split == "train":
        for case_id, flags in patterns.items():
            if all(flags):
                _insert(
                    conn,
                    "task_graduated",
                    clock.next(),
                    agent_id=agent_id,
                    agent_version=version,
                    case_id=case_id,
                    version=version,
                )


def build(
    conn: sqlite3.Connection, root: Path, *, ablation: bool = False
) -> SeededLedger:
    """Seed the ledger and the files on disk. Returns the handles tests need."""
    create_schema(conn)
    clock = _Clock()
    root = Path(root)

    conn.execute(
        "INSERT INTO agents (agent_id, goal, domain, evaluator_id, current_version, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            AGENT_ID,
            "Triage open issues on Untrivial-ai/agent-orchestrator",
            "github_triage",
            EVALUATOR_ID,
            1,
            "2026-09-06T09:59:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO agents (agent_id, goal, domain, evaluator_id, current_version, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            AGENT_B_ID,
            "Triage inbound support tickets",
            "ticket_triage",
            "ticket_triage",
            0,
            "2026-09-06T09:59:30Z",
        ),
    )

    _write_jsonl(
        root / "evaluators" / EVALUATOR_ID / "cases.jsonl",
        [
            {
                "id": "c1",
                "split": "train",
                "input": {"issue": 101},
                "expected": {"labels": ["bug"], "component": "core"},
                "reference_output": {"labels": ["bug"], "component": "core"},
                "tags": ["easy"],
            },
            {
                "id": "c2",
                "split": "train",
                "input": {"issue": 102},
                "expected": {"labels": ["bug"], "component": "core"},
                "reference_output": {"labels": ["bug"], "component": "core"},
                "tags": ["easy"],
            },
            {
                "id": "c3",
                "split": "train",
                "input": {"issue": 103},
                "expected": {"labels": ["bug"], "component": "core"},
                "reference_output": {"labels": ["bug"], "component": "core"},
                "tags": ["duplicate"],
            },
            {
                "id": "c4",
                "split": "train",
                "input": {"issue": 104},
                "expected": {"labels": ["bug", "windows"], "component": "pty"},
                "reference_output": {"labels": ["bug", "windows"], "component": "pty"},
                "tags": ["windows"],
            },
            {
                "id": "h1",
                "split": "holdout",
                "input": {"issue": 201},
                "expected": {"labels": ["bug"], "component": "core"},
                "reference_output": {"labels": ["bug"], "component": "core"},
                "tags": ["easy"],
            },
            {
                "id": "h2",
                "split": "holdout",
                "input": {"issue": 202},
                "expected": {"labels": ["bug"], "component": "core"},
                "reference_output": {"labels": ["bug"], "component": "core"},
                "tags": ["windows"],
            },
        ],
    )

    _insert(
        conn,
        "agent_created",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=0,
        goal="Triage open issues on Untrivial-ai/agent-orchestrator",
        domain="github_triage",
        tools=[
            "github_get_issue_context",
            "github_search_similar_issues",
            "github_get_label_taxonomy",
            "github_find_component_owners",
        ],
        evaluator_id=EVALUATOR_ID,
        orchestration="single",
        applied_lessons=[],
    )

    # v0: empty memory, 9 tool calls per task-execution (2 redundant, 1 error).
    _emit_run(
        conn,
        clock,
        root,
        agent_id=AGENT_ID,
        version=0,
        split="train",
        run_id="run_v0_train",
        patterns=V0_TRAIN,
        cost_usd=0.01,
        latency_base=1000,
        latency_step=100,
        tokens_in=800,
        tokens_out=200,
        tool_calls=9,
        tool_errors=1,
        redundant_tool_calls=2,
        tool_tokens_per_call=50,
        drift={
            ("c3", 1): {
                "kind": "loop",
                "action": "nudge",
                "tokens_at_detection": 9000,
                "evidence": "list_issues(state=open) x3",
            },
            ("c3", 2): {
                "kind": "loop",
                "action": "nudge",
                "tokens_at_detection": 9500,
                "evidence": "list_issues(state=open) x3",
            },
            ("c4", 1): {
                "kind": "budget",
                "action": "abort",
                "tokens_at_detection": 15000,
                "evidence": "cumulative tokens 20143 > 20000",
            },
        },
    )
    _emit_run(
        conn,
        clock,
        root,
        agent_id=AGENT_ID,
        version=0,
        split="holdout",
        run_id="run_v0_holdout",
        patterns=V0_HOLDOUT,
        cost_usd=0.01,
        latency_base=1000,
        latency_step=100,
        tokens_in=800,
        tokens_out=200,
        tool_calls=9,
        tool_errors=1,
        redundant_tool_calls=2,
        tool_tokens_per_call=50,
    )

    # An auto issue for the group the memory fix targets, and a human one.
    _insert(
        conn,
        "issue_opened",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=0,
        issue_id="i1",
        source="auto",
        title="wrong_component on Windows/ConPTY reports",
        failure_signature="wrong_component",
    )
    _insert(
        conn,
        "issue_linked_case",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=0,
        issue_id="i1",
        case_id="c4",
    )
    _insert(
        conn,
        "issue_opened",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=0,
        issue_id="i2",
        source="human",
        title="Duplicate detection misses cross-referenced issues",
    )
    for issue_id, status, signature in (
        ("i1", "open", "wrong_component"),
        ("i2", "fixed", None),
    ):
        conn.execute(
            "INSERT INTO issues (id, agent_id, title, body, screenshot_path, source, status, "
            "failure_signature, created_ts, fixed_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                issue_id,
                AGENT_ID,
                f"issue {issue_id}",
                "body",
                None,
                "auto" if issue_id == "i1" else "human",
                status,
                signature,
                "2026-09-06T10:30:00Z",
                1 if status == "fixed" else None,
            ),
        )

    # Accepted fix 0 -> 1, lever = memory.
    v1_diff = root / "agents" / AGENT_ID / "v1" / "CHANGES.diff"
    _write_text(
        v1_diff,
        "--- a/memory/rules.jsonl\n+++ b/memory/rules.jsonl\n"
        '+{"id": "r1", "rule": "Windows/ConPTY reports get label windows"}\n'
        '+{"id": "r2", "rule": "Paths under src/pty/ map to component pty"}\n'
        '+{"id": "r3", "rule": "Crash reports without a stack trace are priority p2"}\n',
    )
    _insert(
        conn,
        "fix_proposed",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=0,
        lever="memory",
        issue_id="i1",
        from_version=0,
        to_version=1,
        failing_group={
            "signature": "wrong_component",
            "tag": "windows",
            "case_ids": ["c4"],
            "count": 1,
        },
        hypothesis="The agent never learned that src/pty/ paths belong to the pty component.",
        diagnosis="Windows/ConPTY issues are labelled core because no rule maps paths to components.",
        diff_path="agents/agent_demo/v1/CHANGES.diff",
        diff_summary="+3 rules, +1 tool note",
        files_touched=["memory/rules.jsonl", "memory/tool_notes.jsonl"],
        metric_signal="tool_calls_per_task fell from 9 to 4 once path-to-component rules were injected",
    )
    for entry_id, note, confidence in (
        ("r1", "Windows/ConPTY reports get label windows", 0.9),
        ("r2", "Paths under src/pty/ map to component pty", 0.8),
        ("r3", "Crash reports without a stack trace are priority p2", 0.4),
    ):
        _insert(
            conn,
            "memory_written",
            clock.next(),
            agent_id=AGENT_ID,
            agent_version=1,
            entry_id=entry_id,
            kind="rule",
            source="reflection",
            evidence_case_ids=["c4"],
            version=1,
            rule=note,
            confidence=confidence,
        )
    _insert(
        conn,
        "memory_written",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=1,
        entry_id="t1",
        kind="tool_note",
        source="reflection",
        evidence_case_ids=["c3"],
        version=1,
        note="github_search_similar_issues: pass state=all when hunting duplicates",
    )
    _write_jsonl(root / "agents" / AGENT_ID / "v0" / "memory" / "rules.jsonl", [])
    _write_jsonl(
        root / "agents" / AGENT_ID / "v1" / "memory" / "rules.jsonl",
        [
            {
                "id": "r1",
                "rule": "Windows/ConPTY reports get label windows",
                "scope_keywords": ["windows", "conpty"],
                "evidence_case_ids": ["c4"],
                "confidence": 0.9,
                "hits": 14,
                "misses": 1,
                "created_version": 1,
                "source": "reflection",
                "demoted": False,
            },
            {
                "id": "r2",
                "rule": "Paths under src/pty/ map to component pty",
                "scope_keywords": ["pty", "terminal"],
                "evidence_case_ids": ["c4"],
                "confidence": 0.8,
                "hits": 9,
                "misses": 0,
                "created_version": 1,
                "source": "reflection",
                "demoted": False,
            },
            {
                "id": "r3",
                "rule": "Crash reports without a stack trace are priority p2",
                "scope_keywords": ["crash"],
                "evidence_case_ids": ["c4"],
                "confidence": 0.4,
                "hits": 1,
                "misses": 2,
                "created_version": 1,
                "source": "reflection",
                "demoted": True,
            },
        ],
    )
    _write_jsonl(
        root / "agents" / AGENT_ID / "v1" / "memory" / "episodes.jsonl",
        [
            {
                "version": 1,
                "run_id": "run_v0_train",
                "one_line_reflection": "c4 keeps landing on component=core; nothing maps pty paths.",
            }
        ],
    )

    _insert(
        conn,
        "fix_accepted",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=1,
        lever="memory",
        to_version=1,
        pass_at_1_before=2 / 3,
        pass_at_1_after=5 / 6,
        pass_pow_k_before=0.5,
        pass_pow_k_after=0.75,
        group_pass_before=0.0,
        group_pass_after=1 / 3,
        holdout_pass_at_1_after=5 / 6,
        holdout_pass_pow_k_after=0.5,
        cost_per_run_before=0.12,
        cost_per_run_after=0.06,
        tool_calls_per_task_before=9,
        tool_calls_per_task_after=4,
    )

    # v1: memory in play, 4 tool calls per task-execution, rules injected, no redundancy.
    _emit_run(
        conn,
        clock,
        root,
        agent_id=AGENT_ID,
        version=1,
        split="train",
        run_id="run_v1_train",
        patterns=V1_TRAIN,
        cost_usd=0.005,
        latency_base=500,
        latency_step=50,
        tokens_in=400,
        tokens_out=100,
        tool_calls=4,
        tool_errors=0,
        redundant_tool_calls=0,
        tool_tokens_per_call=60,
        rules=V1_RULES,
        drift={
            ("c4", 1): {
                "kind": "step_limit",
                "action": "abort",
                "tokens_at_detection": 18000,
                "evidence": "13 steps > DRIFT_MAX_STEPS=12",
            }
        },
    )
    _emit_run(
        conn,
        clock,
        root,
        agent_id=AGENT_ID,
        version=1,
        split="holdout",
        run_id="run_v1_holdout",
        patterns=V1_HOLDOUT,
        cost_usd=0.005,
        latency_base=500,
        latency_step=50,
        tokens_in=400,
        tokens_out=100,
        tool_calls=4,
        tool_errors=0,
        redundant_tool_calls=0,
        tool_tokens_per_call=60,
        rules=V1_HOLDOUT_RULES,
    )

    # r3 earned more misses than hits and stops being injected.
    _insert(
        conn,
        "memory_demoted",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=1,
        entry_id="r3",
        hits=1,
        misses=2,
        version=1,
    )

    # Rejected fix 1 -> 2, lever = prompt, caught by the gate as a regression.
    _write_text(
        root / "agents" / AGENT_ID / "v2" / "CHANGES.diff",
        "--- a/prompt.md\n+++ b/prompt.md\n-Answer with the labels you are confident in.\n"
        "+Always answer with at least three labels.\n",
    )
    _insert(
        conn,
        "fix_proposed",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=1,
        lever="prompt",
        from_version=1,
        to_version=2,
        failing_group={
            "signature": "wrong_component",
            "tag": "windows",
            "case_ids": ["c4"],
            "count": 1,
        },
        hypothesis="The agent is too conservative and omits secondary labels.",
        diagnosis="Forcing three labels should recover the missing windows label.",
        diff_path="agents/agent_demo/v2/CHANGES.diff",
        diff_summary="prompt: require >= 3 labels",
        files_touched=["prompt.md"],
    )
    _insert(
        conn,
        "fix_rejected",
        clock.next(),
        agent_id=AGENT_ID,
        agent_version=2,
        lever="prompt",
        to_version=2,
        reason="regression",
        regressed_case_ids=["c2"],
        candidate_pass_at_1=0.75,
    )

    for lesson_id, lever, lesson in (
        ("l1", "memory", "Map file paths to components before guessing."),
        ("l2", "prompt", "Do not force a fixed count of labels."),
    ):
        _insert(
            conn,
            "lesson_recorded",
            clock.next(),
            agent_id=AGENT_ID,
            agent_version=1,
            lever=lever,
            lesson_id=lesson_id,
            trigger="label set F1 below threshold",
            lesson=lesson,
            source_agent_id=AGENT_ID,
            source_issue_id="i1",
        )

    # A second domain so /insights/compare has something to group.
    _insert(
        conn,
        "agent_created",
        clock.next(),
        agent_id=AGENT_B_ID,
        agent_version=0,
        goal="Triage inbound support tickets",
        domain="ticket_triage",
        tools=["json_validate"],
        evaluator_id="ticket_triage",
        orchestration="single",
        applied_lessons=["l1"],
    )
    _emit_run(
        conn,
        clock,
        root,
        agent_id=AGENT_B_ID,
        version=0,
        split="train",
        run_id="run_b_v0_train",
        patterns={"b1": [True, True, True], "b2": [False, False, False]},
        cost_usd=0.02,
        latency_base=2000,
        latency_step=100,
        tokens_in=900,
        tokens_out=300,
        tool_calls=6,
        tool_errors=0,
        redundant_tool_calls=0,
        tool_tokens_per_call=70,
    )

    if ablation:
        _write_json(
            root / "reports" / "ablation.json",
            {
                "domain": "ticket_triage",
                "playbook_off": {"holdout_mean": 0.42, "holdout_std": 0.05},
                "playbook_on": {"holdout_mean": 0.58, "holdout_std": 0.04},
                "applied_lessons": ["l1"],
            },
        )

    conn.commit()
    return SeededLedger(
        conn=conn,
        root=root,
        run_ids={
            "v0_train": "run_v0_train",
            "v0_holdout": "run_v0_holdout",
            "v1_train": "run_v1_train",
            "v1_holdout": "run_v1_holdout",
            "b_v0_train": "run_b_v0_train",
        },
    )
