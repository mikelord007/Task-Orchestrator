"""The eval harness.

``run_eval`` runs every task of a split ``trials`` times, emits one
``case_result`` per (task, trial), writes one transcript per (task, trial), and
closes with a ``run_finished`` carrying ``pass_at_1``/``pass_pow_k`` plus
std/min/max, per PLAN_ADDENDUM.md section B.

Definitions (used everywhere, never a bare "accuracy"):

``pass@1``
    Mean per-trial pass rate over tasks - the overall pass rate pooling every
    trial together.
``pass^k`` (k = trials)
    Fraction of tasks that passed *every* trial. Those tasks are the **stable
    pass set**; the gate (W6) accepts a candidate only on ``pass^k``.

**Trial isolation**: each trial gets its own :class:`Transcript` and its own
fresh message list (built in ``run_case``); nothing from another trial, and
nothing from the improver's diagnoses, is ever visible inside a trial.

Threading note: tasks run on a bounded thread pool, but every ledger write
happens on the calling thread as futures complete, so the sqlite connection is
never shared across threads.
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.runtime import memory as mem
from backend.runtime import neatlogs
from backend.runtime.config import Knobs, load_knobs
from backend.runtime.drift import (
    ACTION_ABORT,
    ACTION_NUDGE,
    DriftDecision,
    DriftWatchdog,
)
from backend.runtime.events import (
    EmitFn,
    ReadEventsFn,
    default_emit,
    default_read_events,
    event_id_of,
)
from backend.runtime.loop import CompleteFn, default_complete
from backend.runtime.modes import ModeContext, run_mode
from backend.runtime.package import DEFAULT_AGENTS_DIR, LoadedPackage, load
from backend.runtime.scoring import (
    DEFAULT_EVALUATORS_DIR,
    ScoreFn,
    evaluator_dir,
    load_cases,
    load_scorer,
    score_case,
)
from backend.runtime.signature import (
    bad_output_signature,
    drift_signature,
    failure_signature,
    missing_expected_keys,
)
from backend.runtime.store import resolve_agent
from backend.runtime.transcript import Transcript
from contracts.context import case_scope

DEFAULT_RUNS_DIR = Path("runs")
TRAIN_SPLIT = "train"


@dataclass
class CaseOutcome:
    """One ``case_result`` payload (PLAN_ADDENDUM.md section A)."""

    case_id: str
    trial: int
    passed: bool
    score: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    steps: int
    tool_calls: int
    tool_errors: int
    rules_injected: list[str]
    transcript_path: str
    trace_url: str | None = None
    failure_signature: str | None = None
    drift_event_id: int | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunSummary:
    run_id: str
    agent_id: str
    agent_version: int
    split: str
    trials: int
    case_count: int
    pass_at_1: float
    pass_pow_k: float
    pass_rate_std: float
    pass_rate_min: float
    pass_rate_max: float
    total_cost_usd: float
    p50_latency_ms: int
    p95_latency_ms: int
    drift_count: int
    tokens_saved_by_drift: int
    cases: list[CaseOutcome] = field(default_factory=list)
    demoted_rule_ids: list[str] = field(default_factory=list)
    graduated_case_ids: list[str] = field(default_factory=list)

    def finished_payload(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "trials": self.trials,
            "pass_at_1": self.pass_at_1,
            "pass_pow_k": self.pass_pow_k,
            "pass_rate_std": self.pass_rate_std,
            "pass_rate_min": self.pass_rate_min,
            "pass_rate_max": self.pass_rate_max,
            "total_cost_usd": self.total_cost_usd,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "drift_count": self.drift_count,
            "tokens_saved_by_drift": self.tokens_saved_by_drift,
        }


# -- statistics ---------------------------------------------------------


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def stable_pass_set(outcomes: list[CaseOutcome], trials: int) -> set[str]:
    """Tasks that passed in every trial (the stable pass set; pass^k's numerator)."""
    by_case: dict[str, list[bool]] = {}
    for outcome in outcomes:
        by_case.setdefault(outcome.case_id, []).append(outcome.passed)
    return {
        case_id for case_id, results in by_case.items() if len(results) >= trials and all(results)
    }


def pass_rate_stats(outcomes: list[CaseOutcome], trials: int) -> dict[str, float]:
    """``pass_at_1``, ``pass_pow_k`` and the std/min/max error-bar fields.

    ``pass_at_1`` is the mean over tasks of (passes / trials) - the pooled
    per-trial pass rate. ``pass_pow_k`` is the stable-pass-set fraction.
    ``std``/``min``/``max`` are taken over the per-trial *run-level* pass
    rates, which is what gives the pass@1 band its error bars.
    """
    if not outcomes:
        return {"pass_at_1": 0.0, "pass_pow_k": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    by_case: dict[str, list[bool]] = {}
    by_trial: dict[int, list[bool]] = {}
    for outcome in outcomes:
        by_case.setdefault(outcome.case_id, []).append(outcome.passed)
        by_trial.setdefault(outcome.trial, []).append(outcome.passed)
    case_rates = [sum(1 for p in results if p) / max(1, trials) for results in by_case.values()]
    trial_rates = [
        sum(1 for p in results if p) / len(results) for results in by_trial.values() if results
    ]
    stable = len(stable_pass_set(outcomes, trials))
    return {
        "pass_at_1": round(statistics.fmean(case_rates), 6),
        "pass_pow_k": round(stable / len(by_case), 6) if by_case else 0.0,
        "std": round(statistics.pstdev(trial_rates) if len(trial_rates) > 1 else 0.0, 6),
        "min": round(min(trial_rates), 6) if trial_rates else 0.0,
        "max": round(max(trial_rates), 6) if trial_rates else 0.0,
    }


# -- one task -------------------------------------------------------------


@dataclass
class _CaseRun:
    transcript: Transcript
    decisions: list[DriftDecision]


def _user_message(case: dict[str, Any]) -> str:
    payload = case.get("input")
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return f"Case id: {case.get('id')}\n\nCase input:\n{body}\n"


def run_case(
    *,
    package: LoadedPackage,
    case: dict[str, Any],
    trial: int,
    run_id: str,
    knobs: Knobs,
    scorer: ScoreFn,
    complete: CompleteFn,
    rules: list[dict[str, Any]],
    tool_notes: list[dict[str, Any]],
    demoted_ids: set[str],
    model_strong: str,
    model_cheap: str,
) -> _CaseRun:
    """Run one (task, trial). Never raises; failures become graded failures.

    Trial isolation: a fresh :class:`Transcript` and a fresh message list are
    built right here, every call - nothing carries over between trials.
    """
    case_id = str(case.get("id"))
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    expected_keys = sorted(expected) if expected else []

    selected = mem.select_rules(
        rules,
        mem.case_text(case.get("input")),
        k=knobs.memory_top_k,
        demoted_ids=demoted_ids,
    )
    block = mem.build_memory_block(tool_notes, selected)
    system_prompt = mem.inject_into_prompt(package.prompt, block)

    transcript = Transcript(
        run_id=run_id,
        agent_id=package.agent_id,
        agent_version=package.version,
        case_id=case_id,
        trial=trial,
        orchestration=package.orchestration,
        case_input=case.get("input"),
        expected_keys=expected_keys,
        system_prompt=system_prompt,
        # Runtime-decided, never agent-reported (PLAN_ADDENDUM.md section 0/E).
        rules_injected=[str(r.get("id")) for r in selected],
        tool_notes_injected=[str(n.get("id")) for n in tool_notes],
    )
    decisions: list[DriftDecision] = []
    watchdog = DriftWatchdog(knobs, expected_keys=expected_keys)

    with neatlogs.trace_case(
        f"{package.agent_id}/{case_id}.t{trial}",
        run_id=run_id,
        agent_id=package.agent_id,
        agent_version=package.version,
        case_id=case_id,
        trial=trial,
    ) as trace:
        context = ModeContext(
            package=package,
            transcript=transcript,
            knobs=knobs,
            watchdog=watchdog,
            complete=complete,
            system_prompt=system_prompt,
            user_message=_user_message(case),
            model_strong=model_strong,
            model_cheap=model_cheap,
            on_drift=decisions.append,
        )
        try:
            with case_scope(case):
                result = run_mode(package.orchestration, context)
        except Exception as exc:  # noqa: BLE001 - a broken task is a failed task
            transcript.record_note(f"runtime error: {type(exc).__name__}: {exc}")
            transcript.final_text = None
            transcript.final_output = None
            transcript.passed = False
            transcript.score = 0.0
            transcript.score_notes = f"runtime error: {type(exc).__name__}: {exc}"
            transcript.failure_signature = failure_signature(score_notes=transcript.score_notes)
            transcript.finish()
            return _CaseRun(transcript=transcript, decisions=decisions)
        transcript.trace_url = trace.url

    transcript.final_text = result.final_text
    transcript.final_output = result.final_output

    if result.aborted:
        transcript.passed = False
        transcript.score = 0.0
        transcript.score_notes = f"aborted by the drift watchdog ({result.drift_kind})"
        transcript.failure_signature = drift_signature(result.drift_kind or "unknown")
    elif result.final_output is None:
        transcript.passed = False
        transcript.score = 0.0
        transcript.score_notes = "final answer was not parseable as JSON"
        transcript.failure_signature = bad_output_signature()
    else:
        # Outcomes, not paths: the grader reads the final output only. Tool
        # calls/errors/tokens/latency/drift are tracked metrics, never graders.
        scored = score_case(scorer, expected, result.final_output)
        transcript.passed = scored.passed
        transcript.score = scored.score
        transcript.score_notes = scored.notes
        transcript.failure_signature = (
            None
            if scored.passed
            else failure_signature(
                score_notes=scored.notes,
                first_tool_error=transcript.first_tool_error,
                missing_keys=missing_expected_keys(expected, result.final_output),
            )
        )
    transcript.finish()
    return _CaseRun(transcript=transcript, decisions=decisions)


# -- the run ------------------------------------------------------------


def run_eval(
    agent_id: str,
    version: int | None = None,
    split: str = TRAIN_SPLIT,
    trials: int | None = None,
    *,
    package: LoadedPackage | None = None,
    evaluator_id: str | None = None,
    evaluator_path: Path | str | None = None,
    knobs: Knobs | None = None,
    complete: CompleteFn | None = None,
    emit: EmitFn | None = None,
    read_events: ReadEventsFn | None = None,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
    agents_dir: Path | str = DEFAULT_AGENTS_DIR,
    evaluators_dir: Path | str = DEFAULT_EVALUATORS_DIR,
    model_strong: str | None = None,
    model_cheap: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    run_id: str | None = None,
) -> RunSummary:
    """Run one split of an agent's eval suite at ``trials`` repetitions."""
    knobs = knobs or load_knobs()
    trials = int(trials or knobs.eval_trials)
    emit = emit or default_emit
    complete = complete or default_complete
    read_events = read_events or default_read_events

    agent_row = resolve_agent(agent_id) if (package is None or evaluator_path is None) else {}
    if package is None:
        version = version if version is not None else agent_row.get("current_version", 0)
        package = load(agent_id, int(version or 0), agents_dir)
    version = package.version

    if evaluator_path is None:
        evaluator_id = (
            evaluator_id or agent_row.get("evaluator_id") or package.config.get("evaluator_id")
        )
        if not evaluator_id:
            raise ValueError(f"no evaluator_id known for agent {agent_id}")
        evaluator_path = evaluator_dir(str(evaluator_id), evaluators_dir)
    cases = load_cases(evaluator_path, split)
    scorer = load_scorer(evaluator_path)

    import os

    model_strong = model_strong or str(
        package.config.get("model_strong") or os.environ.get("LLM_MODEL_STRONG") or "strong"
    )
    model_cheap = model_cheap or str(
        package.config.get("model_cheap") or os.environ.get("LLM_MODEL_CHEAP") or "cheap"
    )

    memory = mem.load_memory(package.directory)
    demoted_ids = _demoted_rule_ids(read_events, agent_id)
    previous_stable = (
        _stable_set_from_ledger(read_events, agent_id, version - 1, split, trials)
        if split == TRAIN_SPLIT and version > 0
        else set()
    )

    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
    emit(
        "run_started",
        agent_id=agent_id,
        agent_version=version,
        run_id=run_id,
        split=split,
        case_count=len(cases),
        trials=trials,
    )

    tasks = [(case, trial) for case in cases for trial in range(trials)]
    outcomes: list[CaseOutcome] = []
    drift_count = 0
    tokens_saved = 0
    done = 0
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=max(1, knobs.eval_concurrency)) as pool:
        futures = [
            pool.submit(
                run_case,
                package=package,
                case=case,
                trial=trial,
                run_id=run_id,
                knobs=knobs,
                scorer=scorer,
                complete=complete,
                rules=memory.rules,
                tool_notes=memory.tool_notes,
                demoted_ids=demoted_ids,
                model_strong=model_strong,
                model_cheap=model_cheap,
            )
            for case, trial in tasks
        ]
        for future in futures:
            case_run = future.result()
            transcript = case_run.transcript
            # Ledger writes happen here, on the calling thread only.
            for decision in case_run.decisions:
                drift_count += 1
                if decision.action == ACTION_ABORT:
                    tokens_saved += max(0, knobs.drift_token_budget - decision.tokens_at_detection)
                # payload=: drift_detected.kind collides with emit()'s own
                # positional "kind" name, so it must go through payload=, not
                # **kwargs (backend/ledger/emit.py rejects the bare keyword).
                emitted = emit(
                    "drift_detected",
                    agent_id=agent_id,
                    agent_version=version,
                    run_id=run_id,
                    payload=decision.to_event_payload(
                        case_id=transcript.case_id, trial=transcript.trial
                    ),
                )
                _attach_event_id(transcript, decision, event_id_of(emitted))
            path = transcript.write(runs_dir)
            outcome = CaseOutcome(
                case_id=transcript.case_id,
                trial=transcript.trial,
                passed=bool(transcript.passed),
                score=float(transcript.score or 0.0),
                tokens_in=transcript.tokens_in,
                tokens_out=transcript.tokens_out,
                cost_usd=round(transcript.cost_usd, 8),
                latency_ms=transcript.latency_ms,
                steps=transcript.step_count,
                tool_calls=transcript.tool_calls,
                tool_errors=transcript.tool_errors,
                rules_injected=list(transcript.rules_injected),
                transcript_path=path,
                trace_url=transcript.trace_url,
                failure_signature=transcript.failure_signature,
                drift_event_id=transcript.drift_event_id,
            )
            outcomes.append(outcome)
            emit(
                "case_result",
                agent_id=agent_id,
                agent_version=version,
                run_id=run_id,
                **outcome.payload(),
            )
            done += 1
            if progress is not None:
                progress(done, total)

    stats = pass_rate_stats(outcomes, trials)
    latencies = [float(o.latency_ms) for o in outcomes]
    summary = RunSummary(
        run_id=run_id,
        agent_id=agent_id,
        agent_version=version,
        split=split,
        trials=trials,
        case_count=len(cases),
        pass_at_1=stats["pass_at_1"],
        pass_pow_k=stats["pass_pow_k"],
        pass_rate_std=stats["std"],
        pass_rate_min=stats["min"],
        pass_rate_max=stats["max"],
        total_cost_usd=round(sum(o.cost_usd for o in outcomes), 8),
        p50_latency_ms=int(percentile(latencies, 50)),
        p95_latency_ms=int(percentile(latencies, 95)),
        drift_count=drift_count,
        tokens_saved_by_drift=tokens_saved,
        cases=outcomes,
    )
    emit(
        "run_finished",
        agent_id=agent_id,
        agent_version=version,
        run_id=run_id,
        **summary.finished_payload(),
    )

    if split == TRAIN_SPLIT:
        current_stable = stable_pass_set(outcomes, trials)
        summary.graduated_case_ids = sorted(current_stable - previous_stable)
        for case_id in summary.graduated_case_ids:
            emit(
                "task_graduated",
                agent_id=agent_id,
                agent_version=version,
                case_id=case_id,
                version=version,
            )

    summary.demoted_rule_ids = apply_demotions(
        package=package,
        agent_id=agent_id,
        version=version,
        knobs=knobs,
        emit=emit,
        read_events=read_events,
    )
    return summary


def _attach_event_id(transcript: Transcript, decision: DriftDecision, event_id: int | None) -> None:
    if event_id is None:
        return
    for entry in transcript.drift:
        if (
            entry.get("step") == decision.step
            and entry.get("kind") == decision.kind
            and "event_id" not in entry
        ):
            entry["event_id"] = event_id
            break
    # The last drift event wins: for a nudged case that then passed this points
    # at the nudge, which is exactly what cases_recovered_by_nudge needs.
    transcript.drift_event_id = event_id


def _stable_set_from_ledger(
    read_events: ReadEventsFn, agent_id: str, version: int, split: str, trials: int
) -> set[str]:
    """Stable pass set of an earlier version, read back from ``case_result`` rows."""
    try:
        rows = read_events(agent_id=agent_id, kind="case_result")
    except Exception:  # noqa: BLE001 - an unreadable ledger must not block a run
        return set()
    by_case: dict[str, list[bool]] = {}
    for row in rows:
        payload = row.get("payload") or {}
        if row.get("agent_version") != version:
            continue
        case_id = str(payload.get("case_id"))
        trial = payload.get("trial", payload.get("repeat"))
        if trial is None:
            continue
        by_case.setdefault(case_id, []).append(bool(payload.get("passed")))
    return {
        case_id for case_id, results in by_case.items() if len(results) >= trials and all(results)
    }


# -- memory demotion ----------------------------------------------------


def _demoted_rule_ids(read_events: ReadEventsFn, agent_id: str) -> set[str]:
    try:
        rows = read_events(agent_id=agent_id, kind="memory_demoted")
    except Exception:  # noqa: BLE001 - an unreadable ledger must not block a run
        return set()
    return {str((row.get("payload") or {}).get("entry_id")) for row in rows if row.get("payload")}


def apply_demotions(
    *,
    package: LoadedPackage,
    agent_id: str,
    version: int,
    knobs: Knobs,
    emit: EmitFn,
    read_events: ReadEventsFn,
) -> list[str]:
    """Demote rules whose ledger record shows more misses than hits.

    Hits and misses come from ``case_result.rules_injected`` x ``passed`` across
    every run of this agent - runtime-recorded injections graded by the
    grader, never the agent's own assessment.
    """
    try:
        rows = read_events(agent_id=agent_id, kind="case_result")
    except Exception:  # noqa: BLE001
        return []
    usage = mem.usage_from_case_results([row.get("payload") or {} for row in rows])
    already = _demoted_rule_ids(read_events, agent_id)
    candidates = mem.demotion_candidates(
        usage, already_demoted=already, min_uses=knobs.memory_min_uses
    )
    if not candidates:
        return []
    known = {str(rule.get("id")) for rule in mem.load_memory(package.directory).rules}
    demoted: list[str] = []
    for candidate in candidates:
        if known and candidate.entry_id not in known:
            continue
        emit(
            "memory_demoted",
            agent_id=agent_id,
            agent_version=version,
            lever="memory",
            entry_id=candidate.entry_id,
            hits=candidate.hits,
            misses=candidate.misses,
            version=version,
        )
        demoted.append(candidate.entry_id)
    mem.mark_demoted_on_disk(package.directory, demoted)
    return demoted


__all__ = [
    "ACTION_NUDGE",
    "CaseOutcome",
    "RunSummary",
    "apply_demotions",
    "pass_rate_stats",
    "percentile",
    "run_case",
    "run_eval",
    "stable_pass_set",
]
