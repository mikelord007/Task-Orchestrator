"""Failure grouping -- the pure reads `diagnose` and `reflect` share.

`count` is the number of failing *trials*, not failing tasks: PLAN_ADDENDUM's
"a task failing 2 of 3 trials has weight 2/3" expressed as the plain int the
`FailingGroup` contract wants. That is what ranks the groups, so a task that
fails reliably outranks two that fail occasionally.
"""

from __future__ import annotations

from backend.improver.grouping import (
    failing_case_trials,
    group_train_failures,
    load_case_index,
    load_case_tags,
    resolve_evaluator_path,
    resolve_transcript_path,
)
from backend.tests.improver.conftest import Workspace


def groups_of(workspace: Workspace, version: int = 0):
    evaluator_path = resolve_evaluator_path(workspace.conn, workspace.agent_id)
    return group_train_failures(workspace.conn, workspace.agent_id, version, evaluator_path)


def test_failures_group_by_signature_and_count_failing_trials(workspace: Workspace):
    workspace.seed_run(
        0,
        {
            "t1": [False, False, True],  # 2 failing trials
            "t2": [False, True, True],  # 1
            "t3": [True, True, True],  # 0
        },
        signatures={"t1": "wrong_output", "t2": "wrong_output"},
    )

    (group,) = groups_of(workspace)
    assert group.signature == "wrong_output"
    assert group.count == 3  # 2 + 1 failing trials
    assert group.case_ids == ["t1", "t2"]  # each task appears once


def test_groups_rank_by_failing_trial_count_descending(workspace: Workspace):
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False, True, True], "t3": [False, False, True]},
        signatures={"t1": "sig_a", "t2": "sig_b", "t3": "sig_c"},
    )
    assert [(g.signature, g.count) for g in groups_of(workspace)] == [
        ("sig_a", 3),
        ("sig_c", 2),
        ("sig_b", 1),
    ]


def test_a_drift_signature_is_its_own_first_class_group(workspace: Workspace):
    """`drift:*` is never merged into a neighbouring group: the string is
    distinct, so it groups like any other signature and can be diagnosed on
    its own terms."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False] * 3},
        signatures={"t1": "drift:loop", "t2": "wrong_output"},
    )
    assert sorted(g.signature for g in groups_of(workspace)) == ["drift:loop", "wrong_output"]


def test_a_failure_with_no_signature_still_gets_a_group(workspace: Workspace):
    workspace.seed_run(0, {"t1": [False] * 3}, signatures={"t1": ""})
    (group,) = groups_of(workspace)
    assert group.signature == "unknown_failure"


def test_the_group_tag_is_the_most_common_tag_among_its_tasks(workspace: Workspace):
    """t1 is tagged `billing`; t2 is tagged `crash` and `windows`. With one
    vote each the tie breaks alphabetically, deterministically."""
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [True] * 3})
    (group,) = groups_of(workspace)
    assert group.tag == "billing"

    workspace2_tags = load_case_tags(resolve_evaluator_path(workspace.conn, workspace.agent_id))
    assert workspace2_tags["t2"] == ["crash", "windows"]


def test_a_version_with_no_run_groups_nothing(workspace: Workspace):
    assert groups_of(workspace, version=7) == []


def test_a_run_with_no_failures_groups_nothing(workspace: Workspace):
    workspace.seed_run(0, {"t1": [True] * 3})
    assert groups_of(workspace) == []


# -- evidence lookup ----------------------------------------------------


def test_failing_case_trials_returns_one_failing_trial_per_case(workspace: Workspace):
    workspace.seed_run(0, {"t1": [True, False, False], "t2": [False] * 3, "t3": [True] * 3})
    trials = failing_case_trials(workspace.conn, workspace.agent_id, 0, {"t1", "t2", "t3"})

    assert [(case_id, trial) for case_id, trial, _path in trials] == [("t2", 0), ("t1", 1)]
    for _case_id, _trial, path in trials:
        assert resolve_transcript_path(workspace.root, path).exists()


def test_failing_case_trials_ignores_cases_outside_the_group(workspace: Workspace):
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [False] * 3})
    trials = failing_case_trials(workspace.conn, workspace.agent_id, 0, {"t1"})
    assert [case_id for case_id, _trial, _path in trials] == ["t1"]


def test_failing_case_trials_honours_max_cases(workspace: Workspace):
    workspace.seed_run(0, {"t1": [False] * 3, "t2": [False] * 3, "t3": [False] * 3})
    trials = failing_case_trials(
        workspace.conn, workspace.agent_id, 0, {"t1", "t2", "t3"}, max_cases=2
    )
    assert len(trials) == 2


def test_the_case_index_carries_input_expected_and_split(workspace: Workspace):
    index = load_case_index(resolve_evaluator_path(workspace.conn, workspace.agent_id))
    assert index["t1"]["expected"] == {"category": "billing", "priority": "p1"}
    assert index["t1"]["input"]["text"] == "invoice charged twice"
    assert index["t4"]["split"] == "holdout"
