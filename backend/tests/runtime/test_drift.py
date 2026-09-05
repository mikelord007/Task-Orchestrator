import pytest

from backend.runtime.config import Knobs
from backend.runtime.drift import DriftWatchdog, normalize_args
from backend.runtime.transcript import Transcript

KNOBS = Knobs(
    drift_max_steps=12,
    drift_token_budget=20_000,
    drift_repeat_call_limit=3,
    case_timeout_s=120,
)


def make_transcript() -> Transcript:
    return Transcript(
        run_id="run_1",
        agent_id="a1",
        agent_version=0,
        case_id="c1",
        repeat=0,
        expected_keys=["labels", "component"],
    )


def respond(t: Transcript, text: str = "", tool_calls=None, tokens_out: int = 10) -> None:
    t.record_response(
        model="m",
        text=text,
        tool_calls=tool_calls or [],
        usage={"tokens_in": 10, "tokens_out": tokens_out},
        cost_usd=0.0,
    )


def call_tool(t: Transcript, tool: str, args: dict) -> None:
    t.record_tool_call(tool=tool, args=args, normalized_args=normalize_args(args))


# -- normalization ------------------------------------------------------


def test_normalize_args_is_order_and_whitespace_insensitive():
    assert normalize_args({"a": 1, "b": " X "}) == normalize_args({"b": "x", "a": 1})


def test_normalize_args_distinguishes_different_values():
    assert normalize_args({"page": 1}) != normalize_args({"page": 2})


def test_normalize_args_handles_non_dict_and_nested():
    assert normalize_args(None) == normalize_args(None)
    assert normalize_args({"q": {"z": 1, "a": [2, "B "]}}) == normalize_args(
        {"q": {"a": [2, "b"], "z": 1}}
    )


# -- loop ---------------------------------------------------------------


def test_loop_nudges_on_the_third_identical_call_then_aborts_on_the_fourth():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels"])
    decisions = []
    for _ in range(4):
        respond(t, tool_calls=[{"name": "get_issue", "args": {"number": 7}}])
        call_tool(t, "get_issue", {"number": 7})
        decisions.append(wd.check(t))

    assert decisions[0] is None
    assert decisions[1] is None
    nudge = decisions[2]
    assert nudge is not None
    assert (nudge.kind, nudge.action) == ("loop", "nudge")
    assert nudge.message == (
        "You have called `get_issue` with identical arguments 3 times. "
        "Change approach or answer with what you have."
    )
    assert nudge.evidence["tool"] == "get_issue"
    assert nudge.evidence["count"] == 3
    assert nudge.evidence["limit"] == 3
    # 3 responses of 10 in + 10 out at the moment the nudge fired.
    assert nudge.tokens_at_detection == 60

    abort = decisions[3]
    assert abort is not None
    assert (abort.kind, abort.action) == ("loop", "abort")
    assert abort.evidence["count"] == 4


def test_loop_ignores_calls_with_different_arguments():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels"])
    for page in range(1, 6):
        respond(t, tool_calls=[{"name": "list_issues", "args": {"page": page}}])
        call_tool(t, "list_issues", {"page": page})
        assert wd.check(t) is None


# -- budget -------------------------------------------------------------


def test_budget_aborts_once_cumulative_tokens_exceed_the_budget():
    knobs = Knobs(drift_token_budget=100, drift_max_steps=50, drift_repeat_call_limit=3)
    t = make_transcript()
    wd = DriftWatchdog(knobs, expected_keys=["labels"])
    respond(t, tool_calls=[{"name": "x", "args": {}}], tokens_out=40)
    assert wd.check(t) is None
    respond(t, tool_calls=[{"name": "x", "args": {"p": 1}}], tokens_out=60)
    d = wd.check(t)
    assert d is not None
    assert (d.kind, d.action) == ("budget", "abort")
    assert d.evidence["tokens_used"] == t.tokens_used
    assert d.evidence["budget"] == 100
    assert d.tokens_at_detection == t.tokens_used


# -- step limit ---------------------------------------------------------


def test_step_limit_aborts_once_steps_exceed_the_maximum():
    knobs = Knobs(drift_max_steps=3, drift_token_budget=10**9, drift_repeat_call_limit=99)
    t = make_transcript()
    wd = DriftWatchdog(knobs, expected_keys=["labels"])
    for i in range(3):
        respond(t, tool_calls=[{"name": "x", "args": {"i": i}}])
        assert wd.check(t) is None
    respond(t, tool_calls=[{"name": "x", "args": {"i": 99}}])
    d = wd.check(t)
    assert d is not None
    assert (d.kind, d.action) == ("step_limit", "abort")
    assert d.evidence == {"steps": 4, "max_steps": 3}


# -- off task -----------------------------------------------------------


def test_off_task_nudges_with_the_expected_schema_then_aborts():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels", "component"])
    respond(t, text="Let me think about this problem some more.")
    assert wd.check(t) is None
    respond(t, text="Still thinking about the general shape of the answer.")
    nudge = wd.check(t)
    assert nudge is not None
    assert (nudge.kind, nudge.action) == ("off_task", "nudge")
    assert "labels" in nudge.message and "component" in nudge.message
    assert nudge.evidence["expected_keys"] == ["labels", "component"]
    assert len(nudge.evidence["last_messages"]) == 2

    respond(t, text="I will continue to muse.")
    abort = wd.check(t)
    assert abort is not None
    assert (abort.kind, abort.action) == ("off_task", "abort")


def test_off_task_does_not_fire_when_an_expected_key_is_mentioned():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels", "component"])
    respond(t, text="thinking")
    respond(t, text='{"labels": ["bug"], "component": "cli"}')
    assert wd.check(t) is None


def test_off_task_does_not_fire_when_the_model_is_calling_tools():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels", "component"])
    respond(t, text="looking", tool_calls=[{"name": "a", "args": {}}])
    respond(t, text="looking more", tool_calls=[{"name": "b", "args": {}}])
    assert wd.check(t) is None


def test_off_task_is_disabled_without_expected_keys():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=[])
    respond(t, text="hmm")
    respond(t, text="hmm again")
    assert wd.check(t) is None


# -- timeout ------------------------------------------------------------


def test_timeout_is_reported_as_a_budget_abort():
    knobs = Knobs(case_timeout_s=0)
    t = make_transcript()
    wd = DriftWatchdog(knobs, expected_keys=["labels"])
    respond(t)
    d = wd.check_timeout(t)
    assert d is not None
    assert (d.kind, d.action) == ("budget", "abort")
    assert d.evidence["reason"] == "case_timeout"
    assert d.evidence["timeout_s"] == 0


def test_timeout_not_reported_before_the_deadline():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels"])
    assert wd.check_timeout(t) is None


# -- clean run ----------------------------------------------------------


def test_healthy_transcript_produces_no_drift():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels", "component"])
    respond(t, tool_calls=[{"name": "get_issue", "args": {"number": 1}}])
    call_tool(t, "get_issue", {"number": 1})
    assert wd.check(t) is None
    respond(t, text='{"labels": ["bug"], "component": "cli"}')
    assert wd.check(t) is None


def test_decision_payload_matches_the_drift_detected_event_shape():
    t = make_transcript()
    wd = DriftWatchdog(KNOBS, expected_keys=["labels"])
    for _ in range(3):
        respond(t, tool_calls=[{"name": "x", "args": {}}])
        call_tool(t, "x", {})
        d = wd.check(t)
    payload = d.to_payload(case_id="c1", repeat=2)
    assert set(payload) == {
        "case_id",
        "repeat",
        "step",
        "kind",
        "evidence",
        "action",
        "tokens_at_detection",
    }
    assert payload["case_id"] == "c1"
    assert payload["repeat"] == 2


@pytest.mark.parametrize("kind", ["loop", "budget", "off_task", "step_limit"])
def test_all_four_kinds_are_declared(kind):
    from backend.runtime.drift import DRIFT_KINDS

    assert kind in DRIFT_KINDS
