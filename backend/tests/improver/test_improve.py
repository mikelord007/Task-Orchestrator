"""The `improve` loop: diagnose -> patch -> gate, until one candidate is
accepted or `max_attempts` runs out (PLAN_ADDENDUM.md sections D and E).
FakeLLM only, no network.

One call to `improve` makes at most one accepted version bump. That is the
whole reason the acceptance criterion talks about "5 improve iterations":
re-diagnosing the same stale failure list after an accept would be analyzing
a version that no longer exists.

The scenario every test here shares is the one the demo needs to survive: the
first fix is rejected, the second -- on a different lever -- is accepted, and
both candidates stay on disk with their diffs as evidence.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.improver.improve import improve
from backend.tests.improver.conftest import (
    FakeRunEval,
    JsonLLM,
    Workspace,
    diagnosis_answer,
    reflection_answer,
)

#: Which signature each toy task fails under, kept identical across versions
#: so a group survives a version bump the way a real failure mode does.
SIGNATURES = {"t1": "wrong_output", "t2": "drift:loop", "t3": "wrong_output"}

REFLECTION = reflection_answer(
    rules=[
        {
            "rule": "A duplicated invoice charge is billing at p1.",
            "scope_keywords": ["invoice"],
            "evidence_case_ids": ["t1"],
        }
    ]
)

MEMORY_DIAGNOSIS = diagnosis_answer(
    lever="memory",
    hypothesis="The agent has never seen a duplicate-invoice ticket.",
    proposed_change="Record that duplicate invoice charges are billing at p1.",
)
TOOLS_DIAGNOSIS = diagnosis_answer(
    lever="tools",
    hypothesis="The agent loops on lookup_ticket because the description "
    "never says one call is enough.",
    diagnosis="The tool description invites re-reading.",
    metric_signal="redundant lookup_ticket calls 3.0/task on the failing tasks",
    proposed_change="Say in the description that one call returns the whole record.",
)


class LoopRunEval(FakeRunEval):
    """`run_eval` keyed by `(version, split)` that also writes its run to the
    ledger, exactly as the real one does.

    The loop reads the *prior* version's numbers back out of the ledger, so a
    fake that only returned summaries would leave every version after the
    first with no history to be measured against.
    """

    def __init__(
        self,
        workspace: Workspace,
        by_version: dict[tuple[int, str], Any],
        signatures: dict[str, str] | None = None,
    ) -> None:
        super().__init__({})
        self.workspace = workspace
        self.by_version = by_version
        self.signatures = signatures or SIGNATURES

    def __call__(
        self,
        agent_id: str,
        version: int | None = None,
        split: str = "train",
        trials: int | None = None,
        **kwargs: Any,
    ) -> Any:
        key = (int(version or 0), split)
        self.calls.append({"agent_id": agent_id, "version": version, "split": split})
        patterns = self.by_version.get(key)
        if patterns is None:
            raise AssertionError(f"LoopRunEval has no table for {key}")
        self.workspace.seed_run(
            int(version or 0), patterns, split=split, signatures=self.signatures
        )
        return self.summary(agent_id, int(version or 0), split, patterns)

    @property
    def keys(self) -> list[tuple[int | None, str]]:
        return [(call["version"], call["split"]) for call in self.calls]


@pytest.fixture
def two_group_v0(workspace: Workspace) -> Workspace:
    """v0: t1 fails every trial (wrong_output, 3), t2 fails twice
    (drift:loop, 2), t3 passes every trial. Two groups, ranked."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False, False, True], "t3": [True] * 3},
        signatures=SIGNATURES,
        tools_called={"t2": ["lookup_ticket"] * 4},
    )
    return workspace


def run_improve(
    workspace: Workspace,
    answers: list[Any],
    run_eval: LoopRunEval,
    *,
    max_attempts: int = 3,
    issue_id: str | None = None,
    progress: Any = None,
):
    llm = JsonLLM(answers)
    result = improve(
        workspace.agent_id,
        max_attempts=max_attempts,
        issue_id=issue_id,
        conn=workspace.conn,
        root=workspace.root,
        run_eval=run_eval,
        emit=workspace.emit,
        complete=llm,
        trials=3,
        progress=progress,
    )
    return result, llm


# -- reject, then accept on a different lever ---------------------------


REJECT_THEN_ACCEPT = {
    # v1, the memory attempt: fixes t1 but breaks t3, which stably passed.
    (1, "train"): {"t1": [True] * 3, "t2": [False, False, True], "t3": [True, True, False]},
    # v2, the tools attempt: fixes t2 and keeps t3.
    (2, "train"): {"t1": [False] * 3, "t2": [True] * 3, "t3": [True] * 3},
    (2, "holdout"): {"t4": [True] * 3},
}


def test_a_rejected_fix_is_followed_by_one_on_a_different_lever(two_group_v0: Workspace):
    run_eval = LoopRunEval(two_group_v0, REJECT_THEN_ACCEPT)
    result, llm = run_improve(
        two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval
    )

    assert [(a.attempt, a.lever, a.accepted, a.reason) for a in result.attempts] == [
        (1, "memory", False, "regression"),
        (2, "tools", True, None),
    ]
    assert result.starting_version == 0
    assert result.current_version == 2
    assert result.payload()["improved"] is True
    assert two_group_v0.current_version() == 2

    # Each attempt targeted a different group, in ranked order.
    assert [a.failing_group_signature for a in result.attempts] == ["wrong_output", "drift:loop"]
    # One diagnosis call per group, plus one reflection for the memory lever.
    assert llm.call_count == 3


def test_both_candidates_stay_on_disk_with_their_diffs(two_group_v0: Workspace):
    """Section B: a rejected candidate is evidence, not garbage. Its slot is
    never reused either -- v2 is a fresh directory, not a rewritten v1."""
    run_eval = LoopRunEval(two_group_v0, REJECT_THEN_ACCEPT)
    run_improve(two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval)

    for version in (1, 2):
        package = two_group_v0.package_dir(version)
        assert package.is_dir()
        assert (package / "CHANGES.diff").read_text(encoding="utf-8").strip()

    proposed = two_group_v0.payloads("fix_proposed")
    assert [p["to_version"] for p in proposed] == [1, 2]
    # Both candidates were cut from v0: `improve` diagnoses once per call.
    assert [p["from_version"] for p in proposed] == [0, 0]
    for payload in proposed:
        assert (two_group_v0.root / payload["diff_path"]).exists()


def test_the_ledger_tells_the_whole_story_of_the_loop(two_group_v0: Workspace):
    """What `GET /agents/{id}/fixes` assembles a card per attempt from."""
    run_eval = LoopRunEval(two_group_v0, REJECT_THEN_ACCEPT)
    run_improve(two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval)

    assert len(two_group_v0.payloads("fix_proposed")) == 2
    rejected = two_group_v0.only("fix_rejected")
    accepted = two_group_v0.only("fix_accepted")

    assert rejected["to_version"] == 1
    assert rejected["reason"] == "regression"
    assert rejected["regressed_case_ids"] == ["t3"]
    assert accepted["to_version"] == 2
    assert accepted["pass_at_1_before"] == pytest.approx(4 / 9)
    assert accepted["pass_at_1_after"] == pytest.approx(6 / 9)
    assert accepted["holdout_pass_at_1_after"] == 1.0
    # The memory attempt really did write memory before being rejected.
    assert [m["kind"] for m in two_group_v0.payloads("memory_written")] == ["rule", "episode"]


def test_holdout_is_measured_only_for_the_accepted_candidate(two_group_v0: Workspace):
    run_eval = LoopRunEval(two_group_v0, REJECT_THEN_ACCEPT)
    run_improve(two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval)

    assert run_eval.keys == [(1, "train"), (2, "train"), (2, "holdout")]


# -- nothing is accepted ------------------------------------------------


def test_every_attempt_rejected_leaves_the_current_version_alone(two_group_v0: Workspace):
    """The `fix_rejected` scenario the acceptance criteria ask for: the loop
    tries, records, and changes nothing."""
    run_eval = LoopRunEval(
        two_group_v0,
        {
            (1, "train"): {"t1": [True] * 3, "t2": [False] * 3, "t3": [False] * 3},
            (2, "train"): {"t1": [False] * 3, "t2": [True] * 3, "t3": [True, False, True]},
        },
    )
    result, _llm = run_improve(
        two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval
    )

    assert [a.accepted for a in result.attempts] == [False, False]
    assert [a.reason for a in result.attempts] == ["regression", "regression"]
    assert result.current_version == 0
    assert result.payload()["improved"] is False
    assert two_group_v0.current_version() == 0
    assert two_group_v0.payloads("fix_accepted") == []
    assert len(two_group_v0.payloads("fix_rejected")) == 2


def test_max_attempts_caps_the_loop(two_group_v0: Workspace):
    run_eval = LoopRunEval(
        two_group_v0,
        {(1, "train"): {"t1": [True] * 3, "t2": [False] * 3, "t3": [False] * 3}},
    )
    result, _llm = run_improve(
        two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval, max_attempts=1
    )

    assert len(result.attempts) == 1
    assert run_eval.keys == [(1, "train")]


def test_the_loop_stops_when_it_runs_out_of_diagnoses(two_group_v0: Workspace):
    """Two groups, three permitted attempts: the loop makes two and stops
    rather than re-patching a group it already tried."""
    run_eval = LoopRunEval(
        two_group_v0,
        {
            (1, "train"): {"t1": [True] * 3, "t2": [False] * 3, "t3": [False] * 3},
            (2, "train"): {"t1": [False] * 3, "t2": [True] * 3, "t3": [False] * 3},
        },
    )
    result, _llm = run_improve(
        two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], run_eval, max_attempts=3
    )
    assert len(result.attempts) == 2


def test_a_version_with_nothing_to_fix_returns_an_empty_result(workspace: Workspace):
    workspace.seed_run(0, {"t1": [True] * 3, "t2": [True] * 3})
    run_eval = LoopRunEval(workspace, {})
    result, llm = run_improve(workspace, [MEMORY_DIAGNOSIS], run_eval)

    assert result.attempts == []
    assert result.current_version == 0
    assert llm.call_count == 0
    assert run_eval.calls == []


# -- baselines, issues and progress -------------------------------------


def test_improve_runs_a_baseline_when_the_version_has_no_train_run(workspace: Workspace):
    """`diagnose` and `gate` both need a baseline to read; the loop makes one
    rather than diagnosing an empty ledger."""
    run_eval = LoopRunEval(
        workspace,
        {
            (0, "train"): {"t1": [False] * 3, "t2": [True] * 3},
            (1, "train"): {"t1": [True] * 3, "t2": [True] * 3},
            (1, "holdout"): {"t4": [True] * 3},
        },
    )
    result, _llm = run_improve(workspace, [MEMORY_DIAGNOSIS, REFLECTION], run_eval)

    assert run_eval.keys[0] == (0, "train")
    assert [a.accepted for a in result.attempts] == [True]
    assert result.current_version == 1


def test_an_issue_pulls_its_group_to_the_front(two_group_v0: Workspace):
    """`drift:loop` is the *second*-ranked group; linking it to an issue makes
    the loop try it first, and stamps the issue onto the fix."""
    for case_id in ("t2",):
        two_group_v0.emit(
            "issue_linked_case",
            agent_id=two_group_v0.agent_id,
            ts=two_group_v0.ts(),
            issue_id="iss_9",
            case_id=case_id,
        )

    run_eval = LoopRunEval(
        two_group_v0,
        {
            (1, "train"): {"t1": [False] * 3, "t2": [True] * 3, "t3": [True] * 3},
            (1, "holdout"): {"t4": [True] * 3},
        },
    )
    result, _llm = run_improve(
        two_group_v0,
        [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS],
        run_eval,
        issue_id="iss_9",
    )

    assert [a.failing_group_signature for a in result.attempts] == ["drift:loop"]
    assert result.issue_id == "iss_9"
    assert two_group_v0.only("fix_proposed")["issue_id"] == "iss_9"


def test_an_issue_only_stamps_the_attempts_it_actually_explains(two_group_v0: Workspace):
    """An issue linked to no failing case does not silently claim credit for
    a fix aimed at some other group."""
    two_group_v0.emit(
        "issue_linked_case",
        agent_id=two_group_v0.agent_id,
        ts=two_group_v0.ts(),
        issue_id="iss_other",
        case_id="t9",
    )
    run_eval = LoopRunEval(
        two_group_v0,
        {
            (1, "train"): {"t1": [True] * 3, "t2": [False, False, True], "t3": [True] * 3},
            (1, "holdout"): {"t4": [True] * 3},
        },
    )
    run_improve(
        two_group_v0,
        [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION],
        run_eval,
        issue_id="iss_other",
    )

    assert two_group_v0.only("fix_proposed")["issue_id"] is None


def test_progress_is_reported_once_per_attempt(two_group_v0: Workspace):
    seen: list[tuple[int, int]] = []
    run_eval = LoopRunEval(two_group_v0, REJECT_THEN_ACCEPT)
    run_improve(
        two_group_v0,
        [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION],
        run_eval,
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 3), (2, 3)]


def test_improving_an_unknown_agent_is_an_error(workspace: Workspace):
    with pytest.raises(ValueError, match="unknown agent_id"):
        improve("nope", conn=workspace.conn, run_eval=LoopRunEval(workspace, {}))


# -- successive iterations ----------------------------------------------


def test_a_second_iteration_diagnoses_the_version_that_was_just_installed(
    two_group_v0: Workspace,
):
    """Five improve iterations means five calls, each against whatever the
    current version is by then -- never against a version that has been
    superseded."""
    first = LoopRunEval(
        two_group_v0,
        {
            (1, "train"): {"t1": [True] * 3, "t2": [False, False, True], "t3": [True] * 3},
            (1, "holdout"): {"t4": [True] * 3},
        },
    )
    result, _llm = run_improve(two_group_v0, [MEMORY_DIAGNOSIS, TOOLS_DIAGNOSIS, REFLECTION], first)
    assert result.current_version == 1

    second = LoopRunEval(
        two_group_v0,
        {
            (2, "train"): {"t1": [True] * 3, "t2": [True] * 3, "t3": [True] * 3},
            (2, "holdout"): {"t4": [True] * 3},
        },
    )
    result2, _llm2 = run_improve(two_group_v0, [TOOLS_DIAGNOSIS], second)

    assert result2.starting_version == 1
    assert result2.current_version == 2
    assert [a.from_version for a in result2.attempts] == [1]
    # The remaining group at v1 is the drift one; t1 is fixed and gone.
    assert [a.failing_group_signature for a in result2.attempts] == ["drift:loop"]
    assert two_group_v0.current_version() == 2
