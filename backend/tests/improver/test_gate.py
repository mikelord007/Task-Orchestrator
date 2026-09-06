"""The gate (PLAN_ADDENDUM.md section B). FakeLLM only, no network.

The gate is the only place a candidate earns `current_version`, so these are
the tests that must not be wrong. Section B's rule has two halves and both
are load-bearing:

* **(a)** every task in the prior version's `stable_pass_set` is still in the
  candidate's -- a task that passed every trial before must still pass every
  trial. This is what stops a candidate trading a known-good task for a
  headline number.
* **(b)** candidate `pass@1` >= prior `pass@1` -- no silent slide.

The third case here is the subtle one: a *flaky* task (2 of 3 trials) is by
definition not in the stable set, so it can neither be protected by (a) nor
reported as a regression. A gate that compared "tasks that passed at least
once" instead of the stable set would reject a genuinely better candidate and
stall the whole improvement loop on noise.
"""

from __future__ import annotations

import pytest

from backend.improver.gate import gate
from backend.tests.improver.conftest import FakeRunEval, Workspace

pytestmark = pytest.mark.usefixtures("workspace")

FIX_ACCEPTED_FIELDS = {
    "to_version",
    "pass_at_1_before",
    "pass_at_1_after",
    "pass_pow_k_before",
    "pass_pow_k_after",
    "group_pass_before",
    "group_pass_after",
    "holdout_pass_at_1_after",
    "holdout_pass_pow_k_after",
    "cost_per_run_before",
    "cost_per_run_after",
    "tool_calls_per_task_before",
    "tool_calls_per_task_after",
}


def run_gate(workspace: Workspace, candidate: int, run_eval: FakeRunEval) -> bool:
    return gate(
        workspace.agent_id,
        candidate,
        conn=workspace.conn,
        run_eval=run_eval,
        emit=workspace.emit,
        trials=3,
        root=workspace.root,
    )


# -- accept -------------------------------------------------------------


def test_gate_accepts_a_candidate_that_keeps_every_stable_task_and_lifts_pass_at_1(
    workspace: Workspace,
):
    """v0 stably passes t1/t2 and never passes t3; the candidate fixes t3."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3, "t3": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t3"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3, "t3": [True] * 3},
            "holdout": {"t4": [True, True, False]},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    assert workspace.current_version() == 1
    assert workspace.payloads("fix_rejected") == []

    accepted = workspace.only("fix_accepted")
    assert accepted["to_version"] == 1
    assert accepted["pass_at_1_before"] == pytest.approx(2 / 3)
    assert accepted["pass_at_1_after"] == 1.0
    assert accepted["pass_pow_k_before"] == pytest.approx(2 / 3)
    assert accepted["pass_pow_k_after"] == 1.0
    # The failing group was t3 alone: 0/3 before, 3/3 after.
    assert accepted["group_pass_before"] == 0.0
    assert accepted["group_pass_after"] == 1.0


def test_an_accepted_fix_card_has_every_section_a_field_populated(workspace: Workspace):
    """Section A: the accepted event is the fix card. No nulls, no gaps --
    a judge reads before/after for pass@1, pass^k, the group, holdout, cost
    and tool calls off this one event."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3},
            "holdout": {"t4": [True, True, False]},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True

    accepted = workspace.only("fix_accepted")
    assert set(accepted) == FIX_ACCEPTED_FIELDS
    assert all(accepted[field] is not None for field in FIX_ACCEPTED_FIELDS)
    # Holdout numbers are the candidate's holdout run, not a copy of train.
    assert accepted["holdout_pass_at_1_after"] == pytest.approx(2 / 3)
    assert accepted["holdout_pass_pow_k_after"] == 0.0
    # Cost/tool-call deltas come from the two runs, not from a constant.
    assert accepted["cost_per_run_before"] == pytest.approx(0.01 * 2 * 3)
    assert accepted["cost_per_run_after"] == pytest.approx(0.02 * 2 * 3)
    assert accepted["tool_calls_per_task_before"] == pytest.approx(1.0)
    assert accepted["tool_calls_per_task_after"] == pytest.approx(3.0)


def test_holdout_runs_once_and_only_after_the_train_run_accepted(workspace: Workspace):
    """Holdout is never read by diagnose/reflect and never gates: it is
    measured once, after acceptance, so the accepted event is complete."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    assert run_eval.splits == ["train", "holdout"]
    assert [call["version"] for call in run_eval.calls] == [1, 1]


def test_equal_pass_at_1_is_accepted(workspace: Workspace):
    """Section B says `>=`, not `>`: a candidate that holds the line while
    changing something (a cheaper tool, a clearer prompt) is not a regression."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True, False, False]})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=2)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [False, True, False]},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    accepted = workspace.only("fix_accepted")
    assert accepted["pass_at_1_before"] == pytest.approx(4 / 6)
    assert accepted["pass_at_1_after"] == pytest.approx(4 / 6)


def test_a_tie_is_not_rejected_just_because_the_runtime_rounds(workspace: Workspace):
    """`RunSummary.pass_at_1` is rounded to 6 decimals; the ledger's is not.
    A candidate that ties at a repeating fraction (1/3) reads a hair *below*
    its parent, and must not be rejected as `no_gain` for it."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3, "t3": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [False] * 3, "t3": [False] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_eval.summary("toy", 1, "train", run_eval.by_split["train"]).pass_at_1 == 0.333333
    assert run_gate(workspace, 1, run_eval) is True
    assert workspace.only("fix_accepted")["pass_at_1_after"] == 0.333333


# -- reject -------------------------------------------------------------


def test_gate_rejects_a_regression_even_when_pass_at_1_went_up(workspace: Workspace):
    """The whole point of half (a). t2 stably passed at v0; the candidate
    makes it flaky while lifting overall pass@1 from 2/3 to 8/9. Rejected."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3, "t3": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t3"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [False, True, True], "t3": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is False
    assert workspace.current_version() == 0
    assert workspace.payloads("fix_accepted") == []

    rejected = workspace.only("fix_rejected")
    assert rejected["reason"] == "regression"
    assert rejected["regressed_case_ids"] == ["t2"]
    assert rejected["candidate_pass_at_1"] == pytest.approx(8 / 9)
    # A rejected candidate never costs a holdout run.
    assert run_eval.splits == ["train"]


def test_gate_rejects_a_candidate_that_only_loses_ground(workspace: Workspace):
    """Half (b) with the stable set intact: reason is `no_gain`, and there is
    nothing to list as regressed."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3, "t3": [True, True, False]})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t3"], count=1)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3, "t3": [False] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is False
    rejected = workspace.only("fix_rejected")
    assert rejected["reason"] == "no_gain"
    assert rejected["regressed_case_ids"] == []
    assert rejected["candidate_pass_at_1"] == pytest.approx(6 / 9)
    assert workspace.current_version() == 0


def test_a_broken_candidate_is_a_rejected_candidate_not_a_crashed_gate(workspace: Workspace):
    """A candidate whose package does not even run must not take the loop
    down with it -- it is rejected with `reason=error`."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval({}, raises=RuntimeError("candidate package failed to load"))

    assert run_gate(workspace, 1, run_eval) is False
    rejected = workspace.only("fix_rejected")
    assert rejected["reason"] == "error"
    assert rejected["regressed_case_ids"] == []
    assert workspace.current_version() == 0


# -- flakiness ----------------------------------------------------------


def test_a_flaky_task_is_not_in_the_stable_set_and_cannot_cause_a_false_regression(
    workspace: Workspace,
):
    """The case the gate is most likely to get wrong.

    At v0, t3 passes 2 of 3 trials. It is therefore *not* stable, and the
    candidate is free to lose it entirely: what the gate protects is t1/t2.
    Here the candidate drops t3 to 0/3 but fixes t4 (0/3 -> 3/3), so pass@1
    rises 8/12 -> 9/12 and the fix is accepted. A gate that treated "passed
    at least once at v0" as the protected set would have called t3 a
    regression and rejected a real improvement.
    """
    from backend.ledger.metrics import stable_pass_set

    prior = {
        "t1": [True] * 3,
        "t2": [True] * 3,
        "t3": [True, True, False],  # flaky: 2/3
        "t4": [False] * 3,
    }
    workspace.seed_run(0, prior)
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t4"], count=3)

    assert stable_pass_set(workspace.conn, workspace.agent_id, 0) == {"t1", "t2"}

    run_eval = FakeRunEval(
        {
            "train": {
                "t1": [True] * 3,
                "t2": [True] * 3,
                "t3": [False] * 3,  # the flaky task is lost outright
                "t4": [True] * 3,
            },
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    assert workspace.payloads("fix_rejected") == []
    accepted = workspace.only("fix_accepted")
    assert accepted["pass_at_1_before"] == pytest.approx(8 / 12)
    assert accepted["pass_at_1_after"] == pytest.approx(9 / 12)
    assert workspace.current_version() == 1


def test_a_task_becoming_flaky_is_a_regression_when_it_used_to_be_stable(workspace: Workspace):
    """The mirror image: 3/3 -> 2/3 *is* a regression, because the task was
    in the stable set. Flakiness is only free where it already existed."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3, "t3": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t3"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True, True, False], "t3": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is False
    assert workspace.only("fix_rejected")["regressed_case_ids"] == ["t2"]


def test_a_task_missing_a_trial_never_counts_as_stable(workspace: Workspace):
    """A partial candidate run cannot smuggle a task into the stable set:
    `stable_pass_set` requires every declared trial to be present."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval(
        {
            # t1 only has 2 of the 3 trials recorded -> not stable -> the
            # prior stable {t1} is not preserved -> regression.
            "train": {"t1": [True, True], "t2": [True, True]},
            "holdout": {"t4": [True] * 3},
        },
        declared_trials=3,
    )

    assert run_gate(workspace, 1, run_eval) is False
    assert workspace.only("fix_rejected")["reason"] == "regression"


# -- bookkeeping --------------------------------------------------------


def test_the_gate_reports_the_lever_the_patch_recorded(workspace: Workspace):
    """`gate` never re-derives the lever; it reads back what `patch` wrote,
    so the ledger's `lever` column agrees across the fix's three events."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, lever="tools", case_ids=["t2"])
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    accepted = next(e for e in workspace.events("fix_accepted"))
    assert accepted.lever == "tools"


def test_gate_works_with_no_fix_proposed_on_record(workspace: Workspace):
    """`gate` is callable on its own (an operator re-gating a candidate dir).
    With no `fix_proposed` there is no lever and no failing group, and the
    group rates fall back to 0.0 rather than crashing the accept path."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 1, run_eval) is True
    accepted = workspace.only("fix_accepted")
    assert accepted["group_pass_before"] == 0.0
    assert accepted["group_pass_after"] == 0.0


def test_a_second_gate_run_compares_against_the_newly_accepted_version(workspace: Workspace):
    """After an accept, `current_version` moves and the *next* candidate is
    measured against the version that was just installed -- not against v0."""
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [False] * 3})
    workspace.seed_fix_proposed(from_version=0, to_version=1, case_ids=["t2"], count=3)
    run_eval = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True] * 3},
            "holdout": {"t4": [True] * 3},
        }
    )
    assert run_gate(workspace, 1, run_eval) is True

    # v1's own train run is now on the ledger; v2 must beat *it*.
    workspace.seed_run(1, {"t1": [True] * 3, "t2": [True] * 3})
    workspace.seed_fix_proposed(from_version=1, to_version=2, case_ids=["t2"], count=1)
    second = FakeRunEval(
        {
            "train": {"t1": [True] * 3, "t2": [True, False, True]},
            "holdout": {"t4": [True] * 3},
        }
    )

    assert run_gate(workspace, 2, second) is False
    rejections = workspace.payloads("fix_rejected")
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "regression"
    assert rejections[0]["regressed_case_ids"] == ["t2"]
    assert workspace.current_version() == 1
