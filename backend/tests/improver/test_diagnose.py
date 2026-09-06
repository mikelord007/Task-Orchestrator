"""Diagnose and its validation (PLAN_ADDENDUM.md sections D, E and K).
FakeLLM only, no network.

Two rules from the addendum are enforced by `validate_diagnosis`, and they
are the reason this step is not just "ask the model which lever to pull":

* **Section K** -- a `tools` diagnosis must cite the tracked-metric signal
  that drove it. "The tool description seems unclear" is a hunch; "redundant
  calls 4.2/task" is a measurement. Without one, touching a tool is guessing.
* **Section E/D** -- a `drift:*` group is a tool-use loop or a prompt that
  never made the agent stop and answer. It cannot be fixed by writing down a
  fact (memory) or by changing the orchestration mode, so only `tools` and
  `prompt` are admissible.

`diagnose` itself never drops a group when the model breaks one of these: it
falls back to `prompt` (always valid) and records why, so the caller still
gets one diagnosis per top group.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.improver.diagnose import (
    MAX_GROUPS,
    Diagnosis,
    DiagnosisValidationError,
    diagnose,
    metric_signal_problem,
    observed_tool_usage,
    validate_diagnosis,
)
from backend.tests.improver.conftest import JsonLLM, Workspace, diagnosis_answer
from contracts.events import FailingGroup


def group(signature: str = "wrong_output", **kwargs: Any) -> FailingGroup:
    return FailingGroup(
        signature=signature,
        tag=kwargs.pop("tag", None),
        case_ids=kwargs.pop("case_ids", ["t1"]),
        count=kwargs.pop("count", 1),
    )


def make(
    lever: str,
    *,
    signature: str = "wrong_output",
    metric_signal: str | None = None,
    observed: dict[str, dict[str, float]] | None = None,
):
    return Diagnosis(
        failing_group=group(signature),
        hypothesis="h",
        diagnosis="d",
        lever=lever,
        proposed_change="c",
        metric_signal=metric_signal,
        observed_tool_usage=observed or {},
    )


def run_diagnose(
    workspace: Workspace, answers: list[Any], *, version: int = 0
) -> tuple[list[Diagnosis], JsonLLM]:
    llm = JsonLLM(answers)
    result = diagnose(
        workspace.agent_id, version, conn=workspace.conn, root=workspace.root, complete=llm
    )
    return result, llm


# -- validation ---------------------------------------------------------


def test_a_tools_diagnosis_without_a_metric_signal_is_rejected():
    """Section K, the rule this whole module hangs on."""
    with pytest.raises(DiagnosisValidationError, match="no metric_signal"):
        validate_diagnosis(make("tools"))


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_metric_signal_does_not_count_as_citing_one(blank: str | None):
    with pytest.raises(DiagnosisValidationError, match="no metric_signal"):
        validate_diagnosis(make("tools", metric_signal=blank))


def test_a_tools_diagnosis_with_a_metric_signal_is_accepted():
    validate_diagnosis(make("tools", metric_signal="redundant calls 4.2/task"))


@pytest.mark.parametrize("lever", ["memory", "prompt", "orchestration"])
def test_the_other_levers_need_no_metric_signal(lever: str):
    validate_diagnosis(make(lever))


def test_an_unknown_lever_is_rejected():
    with pytest.raises(DiagnosisValidationError, match="unknown lever"):
        validate_diagnosis(make("vibes"))


@pytest.mark.parametrize("lever", ["memory", "orchestration"])
def test_a_drift_group_cannot_be_diagnosed_as_memory_or_orchestration(lever: str):
    with pytest.raises(DiagnosisValidationError, match="must resolve to"):
        validate_diagnosis(make(lever, signature="drift:loop"))


@pytest.mark.parametrize("signature", ["drift:loop", "drift:budget", "drift:step_limit"])
def test_every_drift_signature_is_held_to_the_same_two_levers(signature: str):
    validate_diagnosis(make("prompt", signature=signature))
    validate_diagnosis(make("tools", signature=signature, metric_signal="repeat calls 3/task"))
    with pytest.raises(DiagnosisValidationError):
        validate_diagnosis(make("memory", signature=signature))


# -- drift groups end to end --------------------------------------------


@pytest.fixture
def drifting_v0(workspace: Workspace) -> Workspace:
    """t1 loops on `lookup_ticket` until the watchdog aborts it."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3, "t3": [True] * 3},
        signatures={"t1": "drift:loop"},
        notes={"t1": "aborted by the drift watchdog (loop)"},
        tools_called={"t1": ["lookup_ticket"] * 4},
    )
    return workspace


def test_a_drift_loop_group_yields_a_tools_lever_with_a_stated_reason(
    drifting_v0: Workspace,
):
    """The model reads the repeat-call metric and rightsizes the tool."""
    result, llm = run_diagnose(
        drifting_v0,
        [
            diagnosis_answer(
                lever="tools",
                hypothesis="The agent calls lookup_ticket over and over because the "
                "description does not say the record is complete after one call.",
                diagnosis="The tool description invites re-reading; nothing tells the "
                "agent it already has everything it needs.",
                metric_signal="redundant lookup_ticket calls 3.0/task before the abort",
                proposed_change="State in the description that one call returns the "
                "whole record and it must not be repeated.",
            )
        ],
    )

    assert len(result) == 1
    diagnosis = result[0]
    assert diagnosis.failing_group.signature == "drift:loop"
    assert diagnosis.lever == "tools"
    assert diagnosis.metric_signal == "redundant lookup_ticket calls 3.0/task before the abort"
    assert diagnosis.proposed_change  # the "stated reason" the fix card shows
    validate_diagnosis(diagnosis)
    # The prompt told the model drift is tools-or-prompt only.
    assert "drift:" in llm.prompt_text(0)


def test_a_drift_group_the_model_calls_memory_is_forced_to_prompt(drifting_v0: Workspace):
    """`diagnose` does not drop the group; it downgrades to the always-valid
    lever and writes the violation into the diagnosis text so the fix card
    shows why."""
    result, _llm = run_diagnose(drifting_v0, [diagnosis_answer(lever="memory")])

    assert len(result) == 1
    assert result[0].lever == "prompt"
    assert "forced lever=prompt" in result[0].diagnosis
    assert "must resolve to" in result[0].diagnosis
    validate_diagnosis(result[0])


def test_a_tools_answer_with_no_metric_signal_is_forced_to_prompt(workspace: Workspace):
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, _llm = run_diagnose(workspace, [diagnosis_answer(lever="tools", metric_signal=None)])

    assert result[0].lever == "prompt"
    assert result[0].metric_signal is None
    assert "no metric_signal" in result[0].diagnosis


# -- metric_signal must be about what the harness observed -------------


def test_a_grounded_metric_signal_survives_onto_a_tools_diagnosis(workspace: Workspace):
    """It names a tool the group actually called and claims nothing the
    harness did not record, so it is a citation rather than a sentence."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, _llm = run_diagnose(
        workspace,
        [
            diagnosis_answer(
                lever="tools",
                metric_signal="lookup_ticket: 1.0 calls per failing trial and no answer after it",
            )
        ],
    )
    assert result[0].lever == "tools"
    assert result[0].metric_signal.startswith("lookup_ticket")
    # The observation the claim was checked against travels with the diagnosis.
    assert result[0].observed_tool_usage == {
        "lookup_ticket": {"calls": 1.0, "errors": 0.0, "redundant": 0.0}
    }


def test_a_metric_signal_naming_no_observed_tool_is_refused(workspace: Workspace):
    """The review's case: the fixture records zero tool errors, the model
    says "invalid-parameter errors 30%". Unchecked, that invented number is
    appended permanently to `fix_proposed`."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, _llm = run_diagnose(
        workspace,
        [diagnosis_answer(lever="tools", metric_signal="invalid-parameter errors 30%")],
    )

    assert result[0].lever == "prompt"
    assert result[0].metric_signal is None
    assert "names none of the tools observed" in result[0].diagnosis


def test_a_metric_signal_naming_a_tool_the_group_never_called_is_refused(
    workspace: Workspace,
):
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, _llm = run_diagnose(
        workspace,
        [
            diagnosis_answer(
                lever="tools",
                metric_signal="github_search_similar_issues: 4.2 redundant calls/task",
            )
        ],
    )

    assert result[0].lever == "prompt"
    assert "github_search_similar_issues" in result[0].diagnosis
    assert "made no tool call" in result[0].diagnosis


def test_an_error_claim_about_a_tool_that_never_errored_is_refused(workspace: Workspace):
    """Naming a real tool is not enough: the *claim* has to be backed too."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3}, tool_errors=0)
    result, _llm = run_diagnose(
        workspace,
        [
            diagnosis_answer(
                lever="tools",
                metric_signal="lookup_ticket: invalid-parameter errors on 30% of calls",
            )
        ],
    )

    assert result[0].lever == "prompt"
    assert "errors=0" in result[0].diagnosis


def test_the_same_error_claim_is_accepted_once_the_errors_are_real(workspace: Workspace):
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3},
        tools_called={"t1": ["lookup_ticket"]},
        tool_errors=1,
    )
    result, _llm = run_diagnose(
        workspace,
        [
            diagnosis_answer(
                lever="tools",
                metric_signal="lookup_ticket: invalid-parameter error on every call",
            )
        ],
    )

    assert result[0].lever == "tools"
    assert result[0].observed_tool_usage["lookup_ticket"]["errors"] == 1.0


def test_a_redundant_call_claim_is_checked_the_same_way(workspace: Workspace):
    """t1 calls the same tool with the same args three times: two redundant."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3},
        tools_called={"t1": ["lookup_ticket"] * 3},
    )
    grounded, _llm = run_diagnose(
        workspace,
        [
            diagnosis_answer(
                lever="tools", metric_signal="lookup_ticket: 2 redundant calls per failing trial"
            )
        ],
    )
    assert grounded[0].lever == "tools"
    assert grounded[0].observed_tool_usage["lookup_ticket"]["redundant"] == 2.0


def test_a_signal_is_let_through_when_there_is_no_observation_to_check_it_against():
    """No readable transcripts means no ground truth. Refusing every tools
    fix for want of evidence would be its own kind of dishonesty -- the
    signal stands, unchecked and visibly so."""
    assert metric_signal_problem("redundant calls 4.2/task", {}) is None
    validate_diagnosis(make("tools", metric_signal="redundant calls 4.2/task"))


def test_observed_tool_usage_counts_calls_errors_and_redundancy_per_tool(
    workspace: Workspace,
):
    """The ground truth itself: three identical `lookup_ticket` calls on the
    failing trial, the last one erroring -- 3 calls, 2 redundant, 1 error."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3},
        tools_called={"t1": ["lookup_ticket"] * 3},
        tool_errors=1,
    )
    observed = observed_tool_usage(
        workspace.conn, workspace.agent_id, 0, group(case_ids=["t1"]), workspace.root
    )
    assert observed == {"lookup_ticket": {"calls": 3.0, "errors": 1.0, "redundant": 2.0}}


def test_observed_tool_usage_is_empty_when_the_group_never_called_a_tool(
    workspace: Workspace,
):
    workspace.seed_run(0, {"t1": [False] * 3}, tools_called={"t1": []})
    assert (
        observed_tool_usage(
            workspace.conn, workspace.agent_id, 0, group(case_ids=["t1"]), workspace.root
        )
        == {}
    )


def test_metric_signal_problem_reports_what_is_wrong_not_just_that_it_is():
    observed = {"lookup_ticket": {"calls": 3.0, "errors": 0.0, "redundant": 0.0}}
    assert metric_signal_problem("lookup_ticket: 3 calls/task", observed) is None
    assert "made no tool call" in (metric_signal_problem("get_issue: 3 calls", observed) or "")
    assert "errors=0" in (
        metric_signal_problem("lookup_ticket: 2 invalid-parameter errors", observed) or ""
    )


# -- ranking and grouping -----------------------------------------------


def test_diagnose_covers_the_top_three_groups_ranked_by_failing_trials(
    workspace: Workspace,
):
    """A task failing 2 of 3 trials weighs 2, not 1 -- `count` is the failing
    trial count, which is what ranks the groups."""
    workspace.seed_run(
        0,
        {
            "t1": [False] * 3,  # wrong_output   -> 3
            "t2": [False, False, True],  # drift:loop -> 2
            "t3": [False, True, True],  # tool_error -> 1
            "t4": [False] * 3,  # wrong_output   -> +3 = 6
        },
        signatures={
            "t1": "wrong_output",
            "t2": "drift:loop",
            "t3": "tool_error:lookup_ticket",
            "t4": "wrong_output",
        },
    )
    result, llm = run_diagnose(workspace, [diagnosis_answer()] * 3)

    assert [d.failing_group.signature for d in result] == [
        "wrong_output",
        "drift:loop",
        "tool_error:lookup_ticket",
    ]
    assert [d.failing_group.count for d in result] == [6, 2, 1]
    assert result[0].failing_group.case_ids == ["t1", "t4"]
    # One STRONG call per group, no more.
    assert llm.call_count == 3


def test_only_the_top_three_groups_are_diagnosed(workspace: Workspace):
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False] * 3, "t3": [False] * 3, "t4": [False] * 3},
        signatures={f"t{i}": f"sig_{i}" for i in range(1, 5)},
    )
    result, llm = run_diagnose(workspace, [diagnosis_answer()] * MAX_GROUPS)

    assert len(result) == MAX_GROUPS == 3
    assert llm.call_count == 3


def test_a_version_with_no_failures_produces_no_diagnoses_and_no_llm_calls(
    workspace: Workspace,
):
    """Empty data is reported as empty, and costs nothing."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3})
    result, llm = run_diagnose(workspace, [diagnosis_answer()])

    assert result == []
    assert llm.call_count == 0


def test_a_version_with_no_run_at_all_produces_no_diagnoses(workspace: Workspace):
    result, llm = run_diagnose(workspace, [diagnosis_answer()])
    assert result == []
    assert llm.call_count == 0


# -- what the model is shown --------------------------------------------


def test_the_prompt_carries_the_groups_evidence_and_the_tool_metrics(
    workspace: Workspace,
):
    """Section D: transcripts plus `tool_call_stats` for those tasks -- the
    measurements a tools diagnosis has to cite are actually in the prompt."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3},
        signatures={"t1": "wrong_output"},
        notes={"t1": "category mismatch: got bug, want billing"},
        tools_called={"t1": ["lookup_ticket", "lookup_ticket"]},
        tool_errors=1,
    )
    _result, llm = run_diagnose(workspace, [diagnosis_answer()])
    text = llm.prompt_text(0)

    assert "signature='wrong_output'" in text
    assert "t1 (trial 0)" in text
    assert "category mismatch: got bug, want billing" in text
    assert "expected=" in text and "got=" in text
    assert "Tool usage stats" in text
    # The group's own tasks, not just the run-wide mean the passing task
    # dilutes: t1 makes one redundant call and one erroring call per trial.
    assert "'group_tasks': {'t1': {'calls': 2.0" in text
    assert "'redundant': 1.0" in text
    assert "'errors': 1.0" in text
    assert "'run_aggregate': {'calls': 1.5" in text
    # Lever preference order is stated, memory first.
    assert "memory" in text and "orchestration" in text


def test_the_prompt_says_pass_fail_already_came_from_the_grader(workspace: Workspace):
    """Section 0 again: the failure analyst is not asked to re-judge."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    _result, llm = run_diagnose(workspace, [diagnosis_answer()])
    assert "pass/fail already came from the grader" in llm.prompt_text(0)


# -- degraded model behaviour -------------------------------------------


def test_a_model_that_never_returns_json_still_yields_a_prompt_diagnosis(
    workspace: Workspace,
):
    """A group must not vanish because one call misbehaved -- the loop still
    gets something gate-able, labelled honestly."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, llm = run_diagnose(workspace, ["nope", "still nope"])

    assert len(result) == 1
    assert result[0].lever == "prompt"
    assert "did not return a usable diagnosis" in result[0].hypothesis
    assert llm.call_count == 2  # the one call plus its one retry


def test_missing_fields_become_honest_placeholders_not_empty_strings(
    workspace: Workspace,
):
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    result, _llm = run_diagnose(workspace, [{"lever": "prompt"}])

    assert result[0].hypothesis == "No hypothesis produced."
    assert result[0].diagnosis == "No diagnosis produced."
    assert result[0].proposed_change == ""
