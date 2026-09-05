from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.transcript import (
    StepKind,
    Transcript,
    TranscriptStep,
    load_transcript,
    transcript_path,
)

STEPS = [
    {"i": 0, "ts": "2026-09-06T11:20:04Z", "kind": "request", "model": "gpt-4o", "messages": []},
    {
        "i": 1,
        "ts": "2026-09-06T11:20:06Z",
        "kind": "response",
        "model": "gpt-4o",
        "text": "",
        "tokens_in": 1840,
        "tokens_out": 42,
    },
    {
        "i": 2,
        "ts": "2026-09-06T11:20:06Z",
        "kind": "tool_call",
        "tool": "get_issue",
        "args": {"number": 412},
    },
    {
        "i": 3,
        "ts": "2026-09-06T11:20:07Z",
        "kind": "tool_return",
        "tool": "get_issue",
        "result": "{}",
    },
    {"i": 4, "ts": "2026-09-06T11:20:08Z", "kind": "nudge", "text": "Change approach."},
]

TRANSCRIPT = {
    "run_id": "r_12",
    "case_id": "issue_412",
    "repeat": 0,
    "agent_id": "a_github_triage",
    "version": 3,
    "started_ts": "2026-09-06T11:20:04Z",
    "finished_ts": "2026-09-06T11:20:11Z",
    "steps": STEPS,
    "final_output": {"labels": ["bug"], "component": "pty"},
    "tokens_in": 4210,
    "tokens_out": 260,
    "tool_calls": 4,
    "tool_errors": 1,
    "rules_injected": ["rule_1a2b3c"],
    "drift": [{"kind": "loop", "step": 4, "action": "nudge"}],
}


def test_transcript_validates():
    t = Transcript.model_validate(TRANSCRIPT)
    assert t.run_id == "r_12"
    assert [s.kind for s in t.steps] == [
        StepKind.request,
        StepKind.response,
        StepKind.tool_call,
        StepKind.tool_return,
        StepKind.nudge,
    ]
    assert t.drift[0].kind == "loop"
    assert t.drift[0].action == "nudge"
    assert t.rules_injected == ["rule_1a2b3c"]


def test_totals_default_to_zero_and_output_may_be_null():
    t = Transcript(
        run_id="r_1",
        case_id="c1",
        repeat=0,
        agent_id="a1",
        version=0,
        started_ts="2026-09-06T00:00:00Z",
        finished_ts="2026-09-06T00:00:01Z",
    )
    assert (t.tokens_in, t.tokens_out, t.tool_calls, t.tool_errors) == (0, 0, 0, 0)
    assert t.final_output is None
    assert t.steps == [] and t.drift == []


def test_steps_accept_extra_observed_detail():
    step = TranscriptStep.model_validate(
        {"i": 0, "ts": "2026-09-06T00:00:00Z", "kind": "tool_return", "cache_hit": True}
    )
    assert step.model_dump()["cache_hit"] is True


def test_unknown_step_kind_is_rejected():
    with pytest.raises(ValidationError):
        TranscriptStep.model_validate({"i": 0, "ts": "t", "kind": "thinking"})


def test_missing_required_field_is_rejected():
    payload = {k: v for k, v in TRANSCRIPT.items() if k != "agent_id"}
    with pytest.raises(ValidationError):
        Transcript.model_validate(payload)


def test_path_convention(tmp_path: Path):
    assert transcript_path("r_12", "issue_412", 2, root=tmp_path) == (
        tmp_path / "r_12" / "issue_412.r2.json"
    )


def test_write_then_load_round_trips(tmp_path: Path):
    t = Transcript.model_validate(TRANSCRIPT)
    path = t.write(root=tmp_path)

    assert path == tmp_path / "r_12" / "issue_412.r0.json"
    assert json.loads(path.read_text(encoding="utf-8"))["case_id"] == "issue_412"
    assert load_transcript(path) == t
