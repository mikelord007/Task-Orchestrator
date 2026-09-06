"""Fixtures for the improver tests. FakeLLM only, no network.

Two deliberate choices shape everything here.

**One real workspace on disk, one real sqlite ledger.** ``reflect`` and
``diagnose`` resolve the evaluator through ``agents.evaluator_id`` and the
process-relative ``evaluators/`` directory, and ``patch`` copies a real agent
package; none of that is injectable. So the ``workspace`` fixture chdirs into
a tmp directory laid out exactly like the repo (``agents/``, ``evaluators/``,
``runs/``) and every module under test runs against it with its own defaults.
Nothing is monkeypatched into place.

**Every ledger write goes through the real ``backend.ledger.emit.emit``.**
``Workspace.emit`` is a thin binding of it to the test's connection, so each
payload this suite seeds -- and each one ``patch``/``gate`` emit -- is
validated against ``contracts/events.py`` for real. A payload shape that
would be rejected in production is rejected here too.

The only thing faked is the LLM (``JsonLLM``, replaying through the project's
``FakeLLM``) and, where a test is about the gate's *decision* rather than the
runtime, ``run_eval`` (``FakeRunEval``, which returns a genuine
``RunSummary`` built from a hand-written pass/fail table).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# Make ``backend.*`` importable however pytest was invoked.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TOY_AGENT_V0 = FIXTURES / "toy_triage_agent" / "v0"
TOY_EVALUATOR = FIXTURES / "toy_evaluator"

AGENT_ID = "toy"
EVALUATOR_ID = "toy_evaluator"

#: The toy evaluator's splits, so tests do not re-derive them from the file.
TRAIN_CASES = ["t1", "t2", "t3"]
HOLDOUT_CASES = ["t4"]


# --------------------------------------------------------------------------
# a workspace: agents/ + evaluators/ + runs/ + a real ledger
# --------------------------------------------------------------------------


@dataclass
class Workspace:
    """One tmp repo-shaped directory plus the sqlite ledger describing it."""

    root: Path
    conn: sqlite3.Connection
    agent_id: str = AGENT_ID
    evaluator_id: str = EVALUATOR_ID
    _clock: int = 0
    run_ids: list[str] = field(default_factory=list)

    # -- ledger ---------------------------------------------------------

    def emit(self, event_kind: str, *args: Any, **fields: Any) -> int:
        """The real ``emit``, bound to this workspace's connection."""
        from backend.ledger.emit import emit as ledger_emit

        return ledger_emit(event_kind, *args, conn=self.conn, **fields)

    def events(self, kind: str | None = None) -> list[Any]:
        from backend.ledger.query import events

        return events(self.conn, kind=kind)

    def payloads(self, kind: str) -> list[dict[str, Any]]:
        return [event.payload for event in self.events(kind)]

    def only(self, kind: str) -> dict[str, Any]:
        """The single event of ``kind``; fails loudly if there is not exactly one."""
        found = self.payloads(kind)
        assert len(found) == 1, f"expected exactly one {kind!r} event, got {len(found)}"
        return found[0]

    def current_version(self) -> int:
        from backend.ledger.query import agent_row

        row = agent_row(self.conn, self.agent_id)
        assert row is not None
        return int(row["current_version"])

    def set_current_version(self, version: int) -> None:
        self.conn.execute(
            "UPDATE agents SET current_version = ? WHERE agent_id = ?", (version, self.agent_id)
        )
        self.conn.commit()

    # -- packages -------------------------------------------------------

    def package_dir(self, version: int) -> Path:
        return self.root / "agents" / self.agent_id / f"v{version}"

    def ts(self) -> str:
        """Monotonic timestamps so event order is deterministic."""
        self._clock += 1
        return f"2026-09-06T12:{self._clock // 60:02d}:{self._clock % 60:02d}Z"

    # -- runs -----------------------------------------------------------

    def seed_run(
        self,
        version: int,
        patterns: dict[str, list[bool]],
        *,
        split: str = "train",
        run_id: str | None = None,
        signatures: dict[str, str] | None = None,
        notes: dict[str, str] | None = None,
        tools_called: dict[str, list[str]] | None = None,
        default_tools: tuple[str, ...] = ("lookup_ticket",),
        cost_usd: float = 0.01,
        tokens_in: int = 100,
        tokens_out: int = 40,
        latency_ms: int = 500,
        tool_errors: int = 0,
        final_output: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Emit a whole run: ``run_started``, one ``case_result`` per (task,
        trial) with a real transcript on disk, then ``run_finished``.

        ``patterns`` maps case_id -> per-trial pass/fail. ``signatures`` gives
        the ``failure_signature`` for a case's failing trials (defaulting to
        ``"wrong_output"``), which is what ``group_train_failures`` groups on.
        """
        from contracts.transcript import StepKind, Transcript

        run_id = run_id or f"run_v{version}_{split}_{len(self.run_ids)}"
        self.run_ids.append(run_id)
        signatures = signatures or {}
        notes = notes or {}
        tools_called = tools_called or {}
        final_output = final_output or {}
        case_ids = list(patterns)
        trials = len(next(iter(patterns.values()))) if patterns else 0

        self.emit(
            "run_started",
            agent_id=self.agent_id,
            agent_version=version,
            run_id=run_id,
            ts=self.ts(),
            split=split,
            case_count=len(case_ids),
            trials=trials,
        )

        for trial in range(trials):
            for case_id in case_ids:
                passed = patterns[case_id][trial]
                tools = tools_called.get(case_id, list(default_tools))
                steps: list[dict[str, Any]] = []
                for i, tool in enumerate(tools):
                    is_error = i >= len(tools) - tool_errors
                    steps.append(
                        {
                            "i": len(steps),
                            "ts": self.ts(),
                            "kind": StepKind.tool_call,
                            "tool": tool,
                            "args": {"ticket_id": case_id},
                        }
                    )
                    steps.append(
                        {
                            "i": len(steps),
                            "ts": self.ts(),
                            "kind": StepKind.tool_return,
                            "tool": tool,
                            "result": None if is_error else json.dumps({"ticket_id": case_id}),
                            "error": "invalid parameter: ticket_id" if is_error else None,
                        }
                    )
                note = notes.get(
                    case_id, "" if passed else "category mismatch: got bug, want billing"
                )
                transcript = Transcript(
                    run_id=run_id,
                    case_id=case_id,
                    trial=trial,
                    agent_id=self.agent_id,
                    version=version,
                    started_ts=self.ts(),
                    finished_ts=self.ts(),
                    steps=steps,
                    final_output=final_output.get(
                        case_id, {"category": "bug", "priority": "p2"} if not passed else None
                    ),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tool_calls=len(tools),
                    tool_errors=tool_errors,
                    # Extra field, exactly as backend/runtime/transcript.py writes it:
                    # the grader's verdict is on the transcript, and reflection reads it.
                    result={
                        "passed": passed,
                        "score": 1.0 if passed else 0.0,
                        "notes": note,
                        "failure_signature": None
                        if passed
                        else signatures.get(case_id, "wrong_output"),
                        "drift_event_id": None,
                    },
                )
                path = transcript.write(self.root / "runs")
                self.emit(
                    "case_result",
                    agent_id=self.agent_id,
                    agent_version=version,
                    run_id=run_id,
                    ts=self.ts(),
                    case_id=case_id,
                    trial=trial,
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    steps=len(steps),
                    tool_calls=len(tools),
                    tool_errors=tool_errors,
                    transcript_path=str(path.relative_to(self.root)).replace("\\", "/"),
                    failure_signature=None if passed else signatures.get(case_id, "wrong_output"),
                )

        rates = trial_pass_rates(patterns)
        self.emit(
            "run_finished",
            agent_id=self.agent_id,
            agent_version=version,
            run_id=run_id,
            ts=self.ts(),
            split=split,
            trials=trials,
            pass_at_1=mean_of(rates),
            pass_pow_k=stable_fraction(patterns),
            pass_rate_std=0.0,
            pass_rate_min=min(rates) if rates else 0.0,
            pass_rate_max=max(rates) if rates else 0.0,
            total_cost_usd=round(cost_usd * len(case_ids) * trials, 8),
            p50_latency_ms=latency_ms,
            p95_latency_ms=latency_ms,
            drift_count=0,
            tokens_saved_by_drift=0,
        )
        return run_id

    def seed_fix_proposed(
        self,
        *,
        from_version: int,
        to_version: int,
        lever: str = "memory",
        case_ids: list[str] | None = None,
        signature: str = "wrong_output",
        count: int = 3,
    ) -> None:
        """The ``fix_proposed`` ``patch`` would have written, for gate tests
        that exercise the gate in isolation."""
        self.emit(
            "fix_proposed",
            agent_id=self.agent_id,
            agent_version=to_version,
            lever=lever,
            ts=self.ts(),
            from_version=from_version,
            to_version=to_version,
            failing_group={
                "signature": signature,
                "tag": None,
                "case_ids": case_ids if case_ids is not None else ["t3"],
                "count": count,
            },
            hypothesis="The agent has no rule for this ticket shape.",
            diagnosis="Missing memory rule.",
            diff_path=f"agents/{self.agent_id}/v{to_version}/CHANGES.diff",
            diff_summary="memory: +1 rule",
            files_touched=["memory/rules.jsonl"],
        )


def trial_pass_rates(patterns: dict[str, list[bool]]) -> list[float]:
    """Per-trial pass rate over tasks -- pass@1's per-trial series."""
    if not patterns:
        return []
    trials = len(next(iter(patterns.values())))
    return [
        sum(1 for results in patterns.values() if results[trial]) / len(patterns)
        for trial in range(trials)
    ]


def mean_of(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stable_fraction(patterns: dict[str, list[bool]]) -> float:
    if not patterns:
        return 0.0
    return sum(1 for results in patterns.values() if all(results)) / len(patterns)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Workspace]:
    """A repo-shaped tmp directory, chdir'd into, with agent ``toy`` at v0."""
    from backend.db import migrate

    shutil.copytree(TOY_AGENT_V0, tmp_path / "agents" / AGENT_ID / "v0")
    shutil.copytree(TOY_EVALUATOR, tmp_path / "evaluators" / EVALUATOR_ID)
    (tmp_path / "runs").mkdir()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    migrate(conn)
    conn.execute(
        "INSERT INTO agents (agent_id, goal, domain, evaluator_id, current_version, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (AGENT_ID, "Triage toy tickets", "toy", EVALUATOR_ID, 0, "2026-09-06T11:59:00Z"),
    )
    conn.commit()

    monkeypatch.chdir(tmp_path)
    try:
        yield Workspace(root=tmp_path, conn=conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# a fake run_eval
# --------------------------------------------------------------------------


class FakeRunEval:
    """``run_eval`` replaced by a hand-written pass/fail table per split.

    The gate's job is a *decision* over two runs' statistics; the statistics
    themselves are W1/W2's tested code. So these tests hand it real
    ``RunSummary``/``CaseOutcome`` objects, built by the runtime's own
    ``pass_rate_stats``, and assert on the verdict. ``calls`` records what the
    gate asked for, which is how "holdout runs once, and only after an
    accept" is checked.
    """

    def __init__(
        self,
        by_split: dict[str, dict[str, list[bool]]],
        *,
        raises: Exception | None = None,
        cost_usd: float = 0.02,
        tool_calls: int = 3,
        declared_trials: int | None = None,
    ) -> None:
        self.by_split = by_split
        self.raises = raises
        # Normally the declared trial count is however many columns the table
        # has; override it to model a *partial* run (3 trials declared, 2
        # recorded), which the stable-pass set must refuse to trust.
        self.declared_trials = declared_trials
        self.cost_usd = cost_usd
        self.tool_calls = tool_calls
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        agent_id: str,
        version: int | None = None,
        split: str = "train",
        trials: int | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append({"agent_id": agent_id, "version": version, "split": split})
        if self.raises is not None:
            raise self.raises
        patterns = self.by_split.get(split)
        if patterns is None:
            raise AssertionError(f"FakeRunEval has no table for split {split!r}")
        return self.summary(agent_id, version or 0, split, patterns)

    def summary(
        self, agent_id: str, version: int, split: str, patterns: dict[str, list[bool]]
    ) -> Any:
        from backend.runtime.evaluation import CaseOutcome, RunSummary, pass_rate_stats

        trials = self.declared_trials or (len(next(iter(patterns.values()))) if patterns else 0)
        outcomes = [
            CaseOutcome(
                case_id=case_id,
                trial=trial,
                passed=passed,
                score=1.0 if passed else 0.0,
                tokens_in=100,
                tokens_out=40,
                cost_usd=self.cost_usd,
                latency_ms=500,
                steps=4,
                tool_calls=self.tool_calls,
                tool_errors=0,
                rules_injected=[],
                transcript_path=f"runs/cand_{split}/{case_id}.t{trial}.json",
                failure_signature=None if passed else "wrong_output",
            )
            for case_id, results in patterns.items()
            for trial, passed in enumerate(results)
        ]
        stats = pass_rate_stats(outcomes, trials)
        return RunSummary(
            run_id=f"run_cand_{split}",
            agent_id=agent_id,
            agent_version=version,
            split=split,
            trials=trials,
            case_count=len(patterns),
            pass_at_1=stats["pass_at_1"],
            pass_pow_k=stats["pass_pow_k"],
            pass_rate_std=stats["std"],
            pass_rate_min=stats["min"],
            pass_rate_max=stats["max"],
            total_cost_usd=round(self.cost_usd * len(outcomes), 8),
            p50_latency_ms=500,
            p95_latency_ms=500,
            drift_count=0,
            tokens_saved_by_drift=0,
            cases=outcomes,
        )

    @property
    def splits(self) -> list[str]:
        return [call["split"] for call in self.calls]


# --------------------------------------------------------------------------
# a fake LLM
# --------------------------------------------------------------------------


class JsonLLM:
    """A ``complete`` that replays scripted JSON answers, one per call.

    Every answer still travels through ``backend.llm.set_client(FakeLLM(...))
    -> backend.llm.complete()``, so the real request marshalling, usage
    accounting and cost maths run for each call -- these tests exercise the
    same path production does, with the network replaced rather than the
    client. ``prompts`` keeps every message list the code under test built,
    which is how the mandated-sentence assertion is made.
    """

    _lock = threading.Lock()

    def __init__(self, answers: list[Any], *, repeat_last: bool = False) -> None:
        self.answers = list(answers)
        self.repeat_last = repeat_last
        self.prompts: list[list[dict[str, Any]]] = []
        self.models: list[str] = []

    def __call__(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from backend import llm as llm_module
        from backend.testing.fake_llm import FakeLLM, ScriptedResponse

        self.prompts.append(messages)
        self.models.append(model)
        index = len(self.prompts) - 1
        if index < len(self.answers):
            answer = self.answers[index]
        elif self.repeat_last and self.answers:
            answer = self.answers[-1]
        else:
            raise AssertionError(
                f"JsonLLM ran out of scripted answers on call {index + 1} "
                f"(scripted {len(self.answers)})"
            )
        text = answer if isinstance(answer, str) else json.dumps(answer)
        with self._lock:
            llm_module.set_client(
                FakeLLM([ScriptedResponse(text=text, tokens_in=200, tokens_out=80)])
            )
            try:
                return llm_module.complete(messages, model=model, tools=tools)
            finally:
                llm_module.reset_client()

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def prompt_text(self, index: int = 0) -> str:
        """Every message of one call, concatenated -- for `in` assertions."""
        return "\n".join(str(m.get("content") or "") for m in self.prompts[index])


def reflection_answer(
    rules: list[dict[str, Any]] | None = None, tool_notes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"rules": rules or [], "tool_notes": tool_notes or []}


def diagnosis_answer(
    *,
    lever: str = "memory",
    hypothesis: str = "The agent never learned this ticket shape.",
    diagnosis: str = "No memory rule covers billing tickets.",
    proposed_change: str = "Add a rule mapping duplicate invoices to billing/p1.",
    metric_signal: str | None = None,
) -> dict[str, Any]:
    return {
        "hypothesis": hypothesis,
        "diagnosis": diagnosis,
        "lever": lever,
        "metric_signal": metric_signal,
        "proposed_change": proposed_change,
    }
