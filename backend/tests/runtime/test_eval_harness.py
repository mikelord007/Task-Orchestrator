"""End-to-end eval-harness tests. FakeLLM only, no network."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backend.runtime.evaluation import run_eval
from backend.runtime.modes import PLANNER_INSTRUCTION
from backend.tests.runtime.scripted_llm import ScriptedLLM, response, tool_call

ANSWERS = {
    "t1": {"category": "billing", "priority": "p1"},
    "t2": {"category": "bug", "priority": "p0"},
    "t3": {"category": "feature", "priority": "p3"},
    "t4": {"category": "account", "priority": "p1"},
}

CASE_RESULT_KEYS = {
    "case_id",
    "trial",
    "repeat",  # legacy alias contracts/events.py syncs onto trial
    "passed",
    "score",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "steps",
    "trace_url",
    "transcript_path",
    "failure_signature",
    "drift_event_id",
    "tool_calls",
    "tool_errors",
    "rules_injected",
    "extra",
}


def evidence_of(drift_payload: dict[str, Any]) -> dict[str, Any]:
    """``drift_detected.evidence`` is a JSON string on the ledger (contracts
    require a plain string); tests want the structured dict back."""
    return json.loads(drift_payload["evidence"])


def seed_case_result(
    ledger, *, agent_version: int = 0, run_id: str = "run_seed", **fields: Any
) -> None:
    """Emit one minimal-but-valid ``case_result`` for tests that only care
    about a handful of fields (pass/fail, rules_injected, ...)."""
    case_id = str(fields.pop("case_id"))
    defaults: dict[str, Any] = {
        "trial": 0,
        "passed": False,
        "score": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "latency_ms": 0,
        "steps": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "transcript_path": f"runs/{run_id}/{case_id}.t0.json",
    }
    defaults.update(fields)
    ledger.emit(
        "case_result",
        agent_id="toy",
        agent_version=agent_version,
        run_id=run_id,
        case_id=case_id,
        **defaults,
    )


RUN_FINISHED_KEYS = {
    "split",
    "trials",
    "pass_at_1",
    "pass_pow_k",
    "pass_rate_std",
    "pass_rate_min",
    "pass_rate_max",
    "total_cost_usd",
    "p50_latency_ms",
    "p95_latency_ms",
    "drift_count",
    "tokens_saved_by_drift",
}


def answer(case_id: str) -> str:
    return json.dumps(ANSWERS.get(case_id, {}))


def lookup_then_answer(case_id: str, turn: int, messages: list[dict[str, Any]]):
    if turn == 0:
        return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": case_id})])
    return response(text=answer(case_id))


def run(package, evaluator_path, ledger, knobs, tmp_path, handler, **kwargs):
    llm = ScriptedLLM(handler)
    summary = run_eval(
        "toy",
        package=package,
        split=kwargs.pop("split", "train"),
        trials=kwargs.pop("trials", 3),
        knobs=knobs,
        evaluator_path=evaluator_path,
        complete=llm.complete,
        emit=ledger.emit,
        read_events=ledger.read,
        runs_dir=tmp_path / "runs",
        **kwargs,
    )
    return summary, llm


# -- acceptance ---------------------------------------------------------


def loops_once_on_t3(case_id: str, turn: int, messages: list[dict[str, Any]]):
    """t3 repeats one call until the watchdog nudges it, then answers."""
    if case_id == "t3":
        if turn < 3:
            return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": "t3"})])
        return response(text=answer("t3"))
    return lookup_then_answer(case_id, turn, messages)


def test_toy_package_runs_end_to_end_at_trials_three(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _llm = run(toy_package, evaluator_path, ledger, knobs, tmp_path, loops_once_on_t3)

    assert len(ledger.of_kind("run_started")) == 1
    assert len(ledger.of_kind("case_result")) == 9
    assert len(ledger.of_kind("run_finished")) == 1
    # One nudge per trial of the one looping case.
    drift = ledger.of_kind("drift_detected")
    assert len(drift) == 3
    assert {e["payload"]["kind"] for e in drift} == {"loop"}
    assert {e["payload"]["action"] for e in drift} == {"nudge"}

    assert ledger.of_kind("run_started")[0]["payload"] == {
        "split": "train",
        "case_count": 3,
        "trials": 3,
    }
    assert summary.pass_at_1 == 1.0
    assert summary.pass_pow_k == 1.0
    assert summary.pass_rate_std == 0.0
    assert summary.case_count == 3
    assert summary.drift_count == 3

    # v0 has no prior version, so every stable task graduates.
    assert summary.graduated_case_ids == ["t1", "t2", "t3"]
    graduated = [e["payload"] for e in ledger.of_kind("task_graduated")]
    assert {g["case_id"] for g in graduated} == {"t1", "t2", "t3"}
    assert all(g["version"] == 0 for g in graduated)

    for event in ledger.of_kind("case_result"):
        assert set(event["payload"]) == CASE_RESULT_KEYS
        assert event["agent_id"] == "toy"
        assert event["run_id"] == summary.run_id
    assert set(ledger.of_kind("run_finished")[0]["payload"]) == RUN_FINISHED_KEYS


def test_every_tool_call_the_fake_llm_made_is_in_the_transcript(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _llm = run(toy_package, evaluator_path, ledger, knobs, tmp_path, loops_once_on_t3)

    recorded: dict[tuple[str, int], list[str]] = {}
    for outcome in summary.cases:
        data = json.loads(Path(outcome.transcript_path).read_text(encoding="utf-8"))
        recorded[(outcome.case_id, outcome.trial)] = [
            step["tool"] for step in data["steps"] if step["kind"] == "tool_call"
        ]
        returns = [step for step in data["steps"] if step["kind"] == "tool_return"]
        assert len(returns) == len(recorded[(outcome.case_id, outcome.trial)])
        # Token counts come from the API usage field on every response step.
        responses = [step for step in data["steps"] if step["kind"] == "response"]
        assert responses and all(step["tokens_in"] > 0 for step in responses)
        assert data["tokens_in"] == sum(s["tokens_in"] for s in responses)

    for trial in range(3):
        assert recorded[("t1", trial)] == ["lookup_ticket"]
        assert recorded[("t3", trial)] == ["lookup_ticket"] * 3


def test_transcripts_land_at_the_contract_path(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, lookup_then_answer)
    for outcome in summary.cases:
        expected = tmp_path / "runs" / summary.run_id / f"{outcome.case_id}.t{outcome.trial}.json"
        assert Path(outcome.transcript_path) == expected
        assert expected.exists()


def test_every_transcript_validates_against_the_frozen_contract(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    """The whole point of matching contracts.transcript.Transcript's field
    names (i/kind, drift as its own list, result/error as separate optional
    strings, ...) is that a real consumer can load the file back."""
    from contracts.transcript import load_transcript

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, loops_once_on_t3)
    for outcome in summary.cases:
        transcript = load_transcript(outcome.transcript_path)
        assert transcript.case_id == outcome.case_id
        assert transcript.trial == outcome.trial
        assert transcript.tool_calls == outcome.tool_calls
        assert transcript.tool_errors == outcome.tool_errors
        assert {step.kind for step in transcript.steps} <= {
            "request",
            "response",
            "tool_call",
            "tool_return",
            "nudge",
        }


# -- drift --------------------------------------------------------------


def never_stops(case_id: str, turn: int, messages: list[dict[str, Any]]):
    return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": case_id})])


def test_a_looping_agent_is_nudged_then_aborted(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, never_stops, trials=1)

    drift = [e["payload"] for e in ledger.of_kind("drift_detected")]
    assert len(drift) == 6  # 3 cases x (one nudge, then one abort)
    actions = [(d["case_id"], d["action"]) for d in drift]
    assert actions.count(("t1", "nudge")) == 1
    assert actions.count(("t1", "abort")) == 1

    nudge = next(d for d in drift if d["case_id"] == "t1" and d["action"] == "nudge")
    assert nudge["kind"] == "loop"
    assert evidence_of(nudge)["tool"] == "lookup_ticket"
    assert evidence_of(nudge)["count"] == 3
    assert nudge["tokens_at_detection"] > 0

    assert summary.pass_at_1 == 0.0
    assert summary.pass_pow_k == 0.0
    assert summary.tokens_saved_by_drift > 0
    for outcome in summary.cases:
        assert outcome.failure_signature == "drift:loop"
        assert outcome.drift_event_id is not None

    data = json.loads(Path(summary.cases[0].transcript_path).read_text(encoding="utf-8"))
    assert data["aborted"] is True
    assert data["abort_kind"] == "loop"
    assert [d["action"] for d in data["drift"]] == ["nudge", "abort"]
    assert any(
        step["kind"] == "nudge" and "identical arguments" in step["text"] for step in data["steps"]
    )


def test_a_nudged_case_that_then_passes_points_at_the_nudge_event(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    _summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, loops_once_on_t3)
    nudge_ids = {e["id"] for e in ledger.of_kind("drift_detected")}
    recovered = [
        e["payload"]
        for e in ledger.of_kind("case_result")
        if e["payload"]["passed"] and e["payload"]["drift_event_id"] in nudge_ids
    ]
    assert len(recovered) == 3
    assert {r["case_id"] for r in recovered} == {"t3"}


def test_case_timeout_is_recorded_as_a_budget_drift(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, llm = run(
        toy_package,
        evaluator_path,
        ledger,
        replace(knobs, case_timeout_s=0),
        tmp_path,
        lookup_then_answer,
        trials=1,
    )
    drift = [e["payload"] for e in ledger.of_kind("drift_detected")]
    assert len(drift) == 3
    assert {d["kind"] for d in drift} == {"budget"}
    assert {evidence_of(d)["reason"] for d in drift} == {"case_timeout"}
    assert llm.calls == []
    assert all(o.failure_signature == "drift:budget" for o in summary.cases)


def test_step_limit_aborts_a_runaway_case(toy_package, evaluator_path, ledger, knobs, tmp_path):
    # Different args every turn, so `loop` cannot fire and `step_limit` must.
    def always_new_call(case_id: str, turn: int, messages: list[dict[str, Any]]):
        return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": f"{case_id}-{turn}"})])

    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        replace(knobs, drift_max_steps=4),
        tmp_path,
        always_new_call,
        trials=1,
    )
    drift = [e["payload"] for e in ledger.of_kind("drift_detected")]
    assert {d["kind"] for d in drift} == {"step_limit"}
    assert all(o.failure_signature == "drift:step_limit" for o in summary.cases)


def test_off_task_wandering_is_nudged_with_the_expected_schema(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    def musing(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if turn < 2:
            return response(text="Let me reflect on the shape of this ticket.")
        return response(text=answer(case_id))

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, musing, trials=1)
    drift = [e["payload"] for e in ledger.of_kind("drift_detected")]
    assert {d["kind"] for d in drift} == {"off_task"}
    assert {d["action"] for d in drift} == {"nudge"}
    assert all("category" in evidence_of(d)["expected_keys"] for d in drift)
    assert summary.pass_at_1 == 1.0


# -- trials and flakiness -----------------------------------------------


def test_a_flaky_case_produces_spread_and_leaves_the_stable_set(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    state = {"t1_conversations": 0}

    def flaky(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if turn == 0:
            if case_id == "t1":
                state["t1_conversations"] += 1
            return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": case_id})])
        if case_id == "t1" and state["t1_conversations"] == 2:
            return response(text=json.dumps({"category": "bug", "priority": "p1"}))
        return response(text=answer(case_id))

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, flaky)

    assert summary.pass_rate_std > 0
    assert summary.pass_rate_min < summary.pass_rate_max

    # Stable set computed from the events, not from W1's metrics module.
    results: dict[str, list[bool]] = {}
    for event in ledger.of_kind("case_result"):
        results.setdefault(event["payload"]["case_id"], []).append(event["payload"]["passed"])
    stable = {case_id for case_id, passes in results.items() if all(passes)}
    assert stable == {"t2", "t3"}
    assert results["t1"].count(True) == 2


def test_a_trial_never_sees_another_trials_messages(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    """Trial isolation (PLAN_ADDENDUM.md section J): each trial gets a clean
    transcript and a fresh message list. A handler that misbehaved on an
    earlier trial must not leak into a later one."""
    seen_message_counts: list[int] = []

    def count_incoming_messages(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if turn == 0:
            seen_message_counts.append(len(messages))
        if turn == 0:
            return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": case_id})])
        return response(text=answer(case_id))

    run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        count_incoming_messages,
        trials=3,
    )
    # Every trial's first call starts from the same fresh (system, user) pair -
    # no growth across trials, which would indicate leaked state.
    assert seen_message_counts == [2] * 9


# -- graduation -----------------------------------------------------------


def test_a_stable_task_does_not_graduate_twice_across_versions(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    # Seed a prior version (v0) where only t1 and t2 were stably passing.
    for case_id in ("t1", "t2"):
        for trial in range(3):
            seed_case_result(
                ledger, run_id="run_prior", case_id=case_id, trial=trial, passed=True, score=1.0
            )
    for trial in range(3):
        seed_case_result(
            ledger, run_id="run_prior", case_id="t3", trial=trial, passed=trial == 0, score=0.0
        )

    toy_package.version = 1
    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=3,
    )
    # All three are stable at v1, but only t3 is *newly* stable.
    assert summary.pass_pow_k == 1.0
    assert summary.graduated_case_ids == ["t3"]
    graduated = [e["payload"] for e in ledger.of_kind("task_graduated") if e["agent_version"] == 1]
    assert {g["case_id"] for g in graduated} == {"t3"}


# -- tools --------------------------------------------------------------


def test_a_raising_tool_is_reported_to_the_model_and_counted(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    def call_the_broken_tool(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if turn == 0:
            return response(tool_calls=[tool_call("always_fails", {})])
        return response(text=answer(case_id))

    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        call_the_broken_tool,
        trials=1,
    )
    assert summary.pass_at_1 == 1.0
    assert all(o.tool_errors == 1 for o in summary.cases)
    data = json.loads(Path(summary.cases[0].transcript_path).read_text(encoding="utf-8"))
    returned = next(step for step in data["steps"] if step["kind"] == "tool_return")
    assert returned["result"] is None
    assert returned["error"] == "ERROR: ValueError: tool exploded"


def test_an_unknown_tool_becomes_an_error_string_not_a_crash(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    def call_a_ghost(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if turn == 0:
            return response(tool_calls=[tool_call("no_such_tool", {})])
        return response(text=answer(case_id))

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, call_a_ghost, trials=1)
    data = json.loads(Path(summary.cases[0].transcript_path).read_text(encoding="utf-8"))
    returned = next(step for step in data["steps"] if step["kind"] == "tool_return")
    assert returned["result"] is None
    assert "unknown tool 'no_such_tool'" in returned["error"]
    assert all(o.tool_errors == 1 for o in summary.cases)


# -- output parsing -----------------------------------------------------


def test_persistent_unparseable_prose_is_caught_as_off_task_drift_not_bad_output(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    """Expected keys are set, so the model gets two off-task grace turns
    (nudge, then abort) before this would ever be scored bad_output - a
    model that never converges and never mentions the schema is drifting,
    not merely answering badly once."""

    def prose_only(case_id: str, turn: int, messages: list[dict[str, Any]]):
        return response(text="I think this one is probably billing, honestly.")

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, prose_only, trials=1)
    assert summary.pass_at_1 == 0.0
    assert all(o.failure_signature == "drift:off_task" for o in summary.cases)
    drift = [e["payload"] for e in ledger.of_kind("drift_detected")]
    assert {d["kind"] for d in drift} == {"off_task"}
    assert {d["action"] for d in drift} == {"nudge", "abort"}


def test_an_unparseable_answer_fails_with_bad_output_when_off_task_cannot_apply(
    toy_package, evaluator_path, knobs, tmp_path
):
    """With no expected output keys, off-task detection has nothing to check
    against, so an unparseable, tool-less response is scored immediately."""
    from backend.runtime.evaluation import run_case
    from backend.runtime.scoring import load_scorer

    scorer = load_scorer(evaluator_path)
    llm = ScriptedLLM(lambda case_id, turn, messages: response(text="not json at all"))
    case = {"id": "edge", "input": {"ticket_id": "edge"}, "expected": {}}

    case_run = run_case(
        package=toy_package,
        case=case,
        trial=0,
        run_id="run_edge",
        knobs=knobs,
        scorer=scorer,
        complete=llm.complete,
        rules=[],
        tool_notes=[],
        demoted_ids=set(),
        model_strong="strong",
        model_cheap="cheap",
    )
    transcript = case_run.transcript
    assert transcript.final_output is None
    assert transcript.failure_signature == "bad_output"
    assert case_run.decisions == []


def test_a_fenced_json_answer_is_parsed(toy_package, evaluator_path, ledger, knobs, tmp_path):
    def fenced(case_id: str, turn: int, messages: list[dict[str, Any]]):
        return response(text=f"Here you go:\n```json\n{answer(case_id)}\n```")

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, fenced, trials=1)
    assert summary.pass_at_1 == 1.0


def test_a_wrong_answer_gets_a_normalized_failure_signature(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    def wrong(case_id: str, turn: int, messages: list[dict[str, Any]]):
        return response(text=json.dumps({"category": "other", "priority": "p9"}))

    summary, _ = run(toy_package, evaluator_path, ledger, knobs, tmp_path, wrong, trials=2)
    signatures = {o.failure_signature for o in summary.cases}
    assert signatures == {"field mismatch category, priority"}


# -- orchestration modes ------------------------------------------------


def test_planner_worker_records_the_planning_call(
    toy_package_dir, evaluator_path, ledger, knobs, tmp_path
):
    from backend.runtime.package import load_from_dir

    config = (toy_package_dir / "agent.yaml").read_text(encoding="utf-8")
    (toy_package_dir / "agent.yaml").write_text(
        config.replace("orchestration: single", "orchestration: planner_worker"),
        encoding="utf-8",
    )
    package = load_from_dir(toy_package_dir, agent_id="toy", version=0)
    assert package.orchestration == "planner_worker"

    def plan_then_work(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if PLANNER_INSTRUCTION in str(messages[0]["content"]):
            return response(text="1. call lookup_ticket\n2. answer with JSON")
        if turn == 0:
            return response(tool_calls=[tool_call("lookup_ticket", {"ticket_id": case_id})])
        return response(text=answer(case_id))

    summary, _ = run(package, evaluator_path, ledger, knobs, tmp_path, plan_then_work, trials=1)
    assert summary.pass_at_1 == 1.0
    data = json.loads(Path(summary.cases[0].transcript_path).read_text(encoding="utf-8"))
    assert data["orchestration"] == "planner_worker"
    plan_requests = [s for s in data["steps"] if s["kind"] == "request" and s["phase"] == "plan"]
    assert len(plan_requests) == 1
    assert plan_requests[0]["tools"] == []
    # The plan itself isn't one of the five contract step kinds, so it lives
    # in the transcript's own "notes" list, not in "steps".
    plan_note = next(n for n in data["notes"] if "plan" in n)
    assert "lookup_ticket" in plan_note["plan"]
    assert data["llm_calls"] == 3


def test_routing_picks_the_model_per_step(toy_package_dir, evaluator_path, ledger, knobs, tmp_path):
    from backend.runtime.package import load_from_dir

    config = (toy_package_dir / "agent.yaml").read_text(encoding="utf-8")
    (toy_package_dir / "agent.yaml").write_text(
        config.replace("orchestration: single", "orchestration: planner_worker").replace(
            "  act: strong", "  act: cheap"
        ),
        encoding="utf-8",
    )
    package = load_from_dir(toy_package_dir, agent_id="toy", version=0)

    def plan_then_work(case_id: str, turn: int, messages: list[dict[str, Any]]):
        if PLANNER_INSTRUCTION in str(messages[0]["content"]):
            return response(text="1. answer")
        return response(text=answer(case_id))

    _, llm = run(package, evaluator_path, ledger, knobs, tmp_path, plan_then_work, trials=1)
    models = [call["model"] for call in llm.calls]
    assert models[0] == "strong-model"
    assert models[1] == "cheap-model"


# -- memory -------------------------------------------------------------


def test_the_matching_rules_are_injected_and_recorded(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=1,
    )
    injected = {o.case_id: o.rules_injected for o in summary.cases}
    assert injected["t1"] == ["r_billing"]
    assert injected["t2"] == ["r_windows"]
    assert injected["t3"] == ["r_feature"]

    for event in ledger.of_kind("case_result"):
        assert event["payload"]["rules_injected"] == injected[event["payload"]["case_id"]]

    data = json.loads(Path(summary.cases[0].transcript_path).read_text(encoding="utf-8"))
    assert "=== AGENT MEMORY" in data["system_prompt"]
    assert "invoice charged twice is category billing" in data["system_prompt"]
    # All tool notes are injected, every case.
    assert data["tool_notes_injected"] == ["tn_lookup"]
    assert "lookup_ticket needs the bare ticket id" in data["system_prompt"]


def test_top_k_bounds_how_many_rules_are_injected(
    toy_package_dir, toy_package, evaluator_path, ledger, tmp_path, knobs
):
    from backend.runtime.package import load_from_dir

    rules_path = toy_package_dir / "memory" / "rules.jsonl"
    extra = [
        json.dumps(
            {
                "id": f"r_extra{i}",
                "rule": f"extra {i}",
                "scope_keywords": ["invoice"],
                "confidence": 0.9,
                "hits": 0,
                "misses": 0,
                "created_version": 0,
                "source": "reflection",
            }
        )
        for i in range(10)
    ]
    rules_path.write_text(
        rules_path.read_text(encoding="utf-8") + "\n".join(extra) + "\n",
        encoding="utf-8",
    )
    package = load_from_dir(toy_package_dir, agent_id="toy", version=0)
    summary, _ = run(
        package,
        evaluator_path,
        ledger,
        replace(knobs, memory_top_k=4),
        tmp_path,
        lookup_then_answer,
        trials=1,
    )
    injected = {o.case_id: o.rules_injected for o in summary.cases}
    assert len(injected["t1"]) == 4


def seed_rule_misses(ledger, entry_id: str, count: int) -> None:
    for index in range(count):
        seed_case_result(ledger, case_id=f"seed{index}", rules_injected=[entry_id])


def test_a_rule_that_misses_more_than_it_hits_is_demoted_exactly_once(
    toy_package, toy_package_dir, evaluator_path, ledger, knobs, tmp_path
):
    seed_rule_misses(ledger, "r_billing", 4)

    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=3,
    )
    demotions = ledger.of_kind("memory_demoted")
    assert len(demotions) == 1
    payload = demotions[0]["payload"]
    assert payload["entry_id"] == "r_billing"
    assert payload["misses"] == 4
    assert payload["hits"] == 3
    assert demotions[0]["lever"] == "memory"
    assert summary.demoted_rule_ids == ["r_billing"]

    on_disk = {
        json.loads(line)["id"]: json.loads(line).get("demoted")
        for line in (toy_package_dir / "memory" / "rules.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert on_disk["r_billing"] is True
    assert on_disk["r_windows"] is not True


def test_a_demoted_rule_is_not_injected_again_and_is_not_demoted_twice(
    toy_package, toy_package_dir, evaluator_path, ledger, knobs, tmp_path
):
    from backend.runtime.package import load_from_dir

    seed_rule_misses(ledger, "r_billing", 4)
    run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=3,
    )

    reloaded = load_from_dir(toy_package_dir, agent_id="toy", version=0)
    second, _ = run(reloaded, evaluator_path, ledger, knobs, tmp_path, lookup_then_answer, trials=1)
    injected = {o.case_id: o.rules_injected for o in second.cases}
    assert injected["t1"] == []
    assert injected["t2"] == ["r_windows"]
    assert len(ledger.of_kind("memory_demoted")) == 1


def test_a_rule_used_fewer_than_four_times_is_not_demoted(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    seed_rule_misses(ledger, "r_windows", 1)
    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=1,
    )
    assert ledger.of_kind("memory_demoted") == []
    assert summary.demoted_rule_ids == []


# -- splits -------------------------------------------------------------


def test_holdout_split_runs_only_holdout_cases(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        split="holdout",
        trials=2,
    )
    assert {o.case_id for o in summary.cases} == {"t4"}
    assert ledger.of_kind("run_started")[0]["payload"]["split"] == "holdout"
    assert ledger.of_kind("run_finished")[0]["payload"]["split"] == "holdout"


def test_progress_callback_reports_every_case_trial(
    toy_package, evaluator_path, ledger, knobs, tmp_path
):
    seen: list[tuple[int, int]] = []
    run(
        toy_package,
        evaluator_path,
        ledger,
        knobs,
        tmp_path,
        lookup_then_answer,
        trials=2,
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(index, 6) for index in range(1, 7)]


@pytest.mark.parametrize("concurrency", [1, 4])
def test_bounded_concurrency_produces_the_same_results(
    toy_package, evaluator_path, ledger, knobs, tmp_path, concurrency
):
    summary, _ = run(
        toy_package,
        evaluator_path,
        ledger,
        replace(knobs, eval_concurrency=concurrency),
        tmp_path,
        lookup_then_answer,
    )
    assert summary.pass_at_1 == 1.0
    assert len(summary.cases) == 9
