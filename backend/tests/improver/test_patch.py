"""`patch`: exactly one lever per attempt, on a real package copy
(PLAN_ADDENDUM.md sections D and K). FakeLLM only, no network.

Two things a judge (and the fix card UI) depend on are asserted for every
lever: `CHANGES.diff` exists inside the candidate directory and
`fix_proposed.diff_path` resolves to it, and the emitted payload carries the
whole section A card -- failing group, hypothesis, diagnosis, lever, diff
path, diff summary, files touched -- with nothing left blank.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.improver.diagnose import Diagnosis
from backend.improver.patch import PatchError, patch
from backend.tests.improver.conftest import JsonLLM, Workspace, reflection_answer
from contracts.agent import Episode, MemoryRule, ToolNote
from contracts.events import FailingGroup

FIX_PROPOSED_FIELDS = {
    "from_version",
    "to_version",
    "lever",
    "failing_group",
    "hypothesis",
    "diagnosis",
    "diff_path",
    "diff_summary",
    "files_touched",
    "issue_id",
    "metric_signal",
    "extra",
}

#: Filled in whenever `patch` is asked for the memory lever.
REFLECTION = reflection_answer(
    rules=[
        {
            "rule": "A duplicated invoice charge is category billing at priority p1.",
            "scope_keywords": ["invoice", "charge", "billing"],
            "evidence_case_ids": ["t1"],
        }
    ],
    tool_notes=[
        {
            "tool": "lookup_ticket",
            "note": "lookup_ticket takes the bare ticket id, not the case id.",
            "evidence": "t1 called it with the case id and got an error back.",
        }
    ],
)


def make_diagnosis(
    lever: str = "memory",
    *,
    case_ids: list[str] | None = None,
    signature: str = "wrong_output",
    metric_signal: str | None = None,
    count: int = 3,
) -> Diagnosis:
    return Diagnosis(
        failing_group=FailingGroup(
            signature=signature, tag="billing", case_ids=case_ids or ["t1"], count=count
        ),
        hypothesis="The agent has never seen a duplicate-invoice ticket and guesses `bug`.",
        diagnosis="No memory rule maps duplicate invoices onto billing/p1.",
        lever=lever,
        proposed_change="Record that duplicate invoice charges are billing at p1.",
        metric_signal=metric_signal,
    )


def run_patch(
    workspace: Workspace,
    diagnosis: Diagnosis,
    *,
    version: int = 0,
    candidate_version: int | None = None,
    answers: list[Any] | None = None,
    issue_id: str | None = None,
) -> tuple[int, JsonLLM]:
    llm = JsonLLM(answers if answers is not None else [REFLECTION])
    candidate = patch(
        workspace.agent_id,
        version,
        diagnosis,
        candidate_version=candidate_version,
        conn=workspace.conn,
        root=workspace.root,
        emit=workspace.emit,
        complete=llm,
        issue_id=issue_id,
    )
    return candidate, llm


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture
def failing_v0(workspace: Workspace) -> Workspace:
    """v0 with t1 failing every trial -- the group every test here patches."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [True] * 3, "t3": [True] * 3},
        signatures={"t1": "wrong_output"},
    )
    return workspace


# -- the diff and the card ----------------------------------------------


@pytest.mark.parametrize(
    ("lever", "metric_signal", "expected_files"),
    [
        (
            "memory",
            None,
            [
                "memory/rules.jsonl",
                "memory/tool_notes.jsonl",
                "memory/episodes.jsonl",
                "agent.yaml",
            ],
        ),
        ("prompt", None, ["prompt.md", "agent.yaml"]),
        (
            "tools",
            "lookup_ticket: 1.0 calls on every failing trial and no answer after it",
            ["tools/lookup.py", "agent.yaml"],
        ),
        # The orchestration lever edits `agent.yaml` itself, so the version
        # bump rides inside that one diff rather than being appended twice.
        ("orchestration", None, ["agent.yaml"]),
    ],
)
def test_every_lever_writes_changes_diff_and_points_fix_proposed_at_it(
    failing_v0: Workspace, lever: str, metric_signal: str | None, expected_files: list[str]
):
    candidate, _llm = run_patch(failing_v0, make_diagnosis(lever, metric_signal=metric_signal))
    assert candidate == 1

    proposed = failing_v0.only("fix_proposed")
    assert proposed["lever"] == lever
    assert proposed["files_touched"] == expected_files

    diff_path = failing_v0.root / proposed["diff_path"]
    assert diff_path.name == "CHANGES.diff"
    assert diff_path.parent == failing_v0.package_dir(1)
    assert diff_path.exists()

    diff = diff_path.read_text(encoding="utf-8")
    for expected_file in expected_files:
        assert f"--- a/{expected_file}" in diff
        assert f"+++ b/{expected_file}" in diff
    assert any(line.startswith("+") and not line.startswith("+++") for line in diff.splitlines())


def test_the_fix_proposed_card_is_complete(failing_v0: Workspace):
    """Section A: every field a judge reads off the card is present, and the
    failing group round-trips unchanged from the diagnosis."""
    diagnosis = make_diagnosis("memory", case_ids=["t1"], count=3)
    run_patch(failing_v0, diagnosis)

    proposed = failing_v0.only("fix_proposed")
    assert set(proposed) == FIX_PROPOSED_FIELDS
    assert proposed["from_version"] == 0
    assert proposed["to_version"] == 1
    assert proposed["failing_group"] == {
        "signature": "wrong_output",
        "tag": "billing",
        "case_ids": ["t1"],
        "count": 3,
    }
    assert proposed["hypothesis"] == diagnosis.hypothesis
    assert proposed["diagnosis"] == diagnosis.diagnosis
    assert proposed["diff_summary"]
    assert proposed["files_touched"]
    # The ledger column mirrors the payload, so `events(lever=...)` works.
    assert failing_v0.events("fix_proposed")[0].lever == "memory"


def test_metric_signal_rides_along_on_a_tools_fix_only(failing_v0: Workspace):
    """Section K: `metric_signal` is the justification for touching a tool.
    It is meaningless on the other levers and must not be copied onto them."""
    run_patch(
        failing_v0,
        make_diagnosis("tools", metric_signal="redundant lookup_ticket calls 4.2/task"),
    )
    assert failing_v0.only("fix_proposed")["metric_signal"] == (
        "redundant lookup_ticket calls 4.2/task"
    )

    run_patch(
        failing_v0,
        make_diagnosis("prompt", metric_signal="redundant lookup_ticket calls 4.2/task"),
        candidate_version=2,
    )
    assert failing_v0.payloads("fix_proposed")[1]["metric_signal"] is None


# -- the candidate package ----------------------------------------------


def test_the_candidate_is_a_full_copy_with_its_version_bumped(failing_v0: Workspace):
    run_patch(failing_v0, make_diagnosis("prompt"))

    v0, v1 = failing_v0.package_dir(0), failing_v0.package_dir(1)
    assert sorted(p.name for p in v1.iterdir()) == sorted(
        [*(p.name for p in v0.iterdir()), "CHANGES.diff"]
    )
    # The inherited memory came along untouched.
    assert (v1 / "memory" / "rules.jsonl").read_text(encoding="utf-8") == (
        v0 / "memory" / "rules.jsonl"
    ).read_text(encoding="utf-8")
    assert yaml.safe_load((v1 / "agent.yaml").read_text(encoding="utf-8"))["version"] == 1
    # v0 is evidence: patching never edits the version it came from.
    assert yaml.safe_load((v0 / "agent.yaml").read_text(encoding="utf-8"))["version"] == 0


def test_patch_refuses_to_overwrite_an_existing_candidate_directory(failing_v0: Workspace):
    """A rejected candidate stays on disk as evidence (section B), so its
    slot is never reused."""
    run_patch(failing_v0, make_diagnosis("prompt"))
    with pytest.raises(PatchError, match="already exists"):
        run_patch(failing_v0, make_diagnosis("prompt"))


# -- memory lever -------------------------------------------------------


def test_memory_lever_appends_valid_jsonl_and_emits_memory_written(failing_v0: Workspace):
    candidate, llm = run_patch(failing_v0, make_diagnosis("memory"))
    memory = failing_v0.package_dir(candidate) / "memory"

    rules = [MemoryRule.model_validate(row) for row in read_jsonl(memory / "rules.jsonl")]
    notes = [ToolNote.model_validate(row) for row in read_jsonl(memory / "tool_notes.jsonl")]
    episodes = [Episode.model_validate(row) for row in read_jsonl(memory / "episodes.jsonl")]

    # v0 shipped 3 rules and 1 tool note; reflection added one of each.
    assert len(rules) == 4
    assert len(notes) == 2
    assert len(episodes) == 1

    new_rule = rules[-1]
    assert new_rule.rule.startswith("A duplicated invoice charge")
    assert new_rule.scope_keywords == ["invoice", "charge", "billing"]
    assert new_rule.evidence_case_ids == ["t1"]
    assert new_rule.confidence == 0.5
    assert new_rule.hits == 0 and new_rule.misses == 0
    assert new_rule.created_version == candidate
    assert new_rule.source == "reflection"
    assert new_rule.demoted is False
    assert new_rule.id.startswith("rule_")

    assert notes[-1].tool == "lookup_ticket"
    assert notes[-1].created_version == candidate
    assert episodes[0].version == candidate
    assert episodes[0].one_line_reflection.startswith("The agent has never seen")

    written = failing_v0.payloads("memory_written")
    assert [w["kind"] for w in written] == ["rule", "tool_note", "episode"]
    assert {w["source"] for w in written} == {"reflection"}
    assert {w["version"] for w in written} == {candidate}
    assert written[0]["entry_id"] == new_rule.id
    assert written[0]["evidence_case_ids"] == ["t1"]
    # Exactly one reflection call for the one group.
    assert llm.call_count == 1


def test_the_episode_is_attributed_to_the_run_that_supplied_the_transcripts(
    failing_v0: Workspace,
):
    """An episode whose `run_id` matches no `run_started`/`case_result`/
    `run_finished` cannot be traced back to the evidence it came from. It is
    the id of the train run reflection actually read, not a fresh uuid."""
    from backend.ledger.query import case_results, runs

    candidate, _llm = run_patch(failing_v0, make_diagnosis("memory"))
    episodes = read_jsonl(failing_v0.package_dir(candidate) / "memory" / "episodes.jsonl")
    run_id = episodes[0]["run_id"]

    known = {run.run_id for run in runs(failing_v0.conn, failing_v0.agent_id)}
    assert run_id in known, f"episode cites {run_id!r}, which is not a run in the ledger"
    assert not run_id.startswith("reflect_")
    # And it is the run whose transcripts the reflection call was shown.
    assert {str(e.get("case_id")) for e in case_results(failing_v0.conn, run_id)} >= {"t1"}


def test_a_memory_fix_from_an_issue_is_sourced_to_that_issue(failing_v0: Workspace):
    candidate, _llm = run_patch(failing_v0, make_diagnosis("memory"), issue_id="iss_7")

    rules = read_jsonl(failing_v0.package_dir(candidate) / "memory" / "rules.jsonl")
    assert rules[-1]["source"] == "issue"
    assert {w["source"] for w in failing_v0.payloads("memory_written")} == {"issue"}
    assert failing_v0.only("fix_proposed")["issue_id"] == "iss_7"


def test_memory_diff_shows_the_appended_jsonl_lines(failing_v0: Workspace):
    candidate, _llm = run_patch(failing_v0, make_diagnosis("memory"))
    diff = (failing_v0.package_dir(candidate) / "CHANGES.diff").read_text(encoding="utf-8")

    assert "--- a/memory/rules.jsonl" in diff
    assert "--- a/memory/tool_notes.jsonl" in diff
    assert "--- a/memory/episodes.jsonl" in diff
    assert "A duplicated invoice charge" in diff

    # Only additions in the memory hunks: memory is append-only, nothing is
    # rewritten. (The trailing `agent.yaml` hunk does rewrite one line -- the
    # version bump -- so the check stops where that hunk starts.)
    memory_part = diff.split("--- a/agent.yaml")[0]
    body = [
        line
        for line in memory_part.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert body and all(line.startswith("+") for line in body)


def test_memory_falls_back_to_prompt_when_reflection_proposes_nothing(failing_v0: Workspace):
    """An attempt must still produce a real, gate-able change. Reflection
    coming back empty is not a reason to burn the attempt."""
    candidate, _llm = run_patch(failing_v0, make_diagnosis("memory"), answers=[reflection_answer()])

    proposed = failing_v0.only("fix_proposed")
    assert proposed["lever"] == "prompt"
    assert proposed["files_touched"] == ["prompt.md", "agent.yaml"]
    assert "fell back to" in proposed["diff_summary"]
    assert failing_v0.payloads("memory_written") == []
    assert "## Lesson" in (failing_v0.package_dir(candidate) / "prompt.md").read_text(
        encoding="utf-8"
    )


def test_memory_written_reports_each_entrys_own_evidence_not_the_whole_group(
    failing_v0: Workspace,
):
    """A tool note supported only by t1 must not be recorded as supported by
    t1 *and* t2. `memory_written` is append-only: the provenance it claims is
    the provenance forever."""
    proposals = reflection_answer(
        rules=[
            {
                "rule": "Duplicate invoice charges are billing at p1.",
                "scope_keywords": ["invoice"],
                "evidence_case_ids": ["t1"],
            }
        ],
        tool_notes=[
            {
                "tool": "lookup_ticket",
                "note": "It takes the bare ticket id.",
                "evidence": "t2 passed the case id and got an error back",
            }
        ],
    )
    candidate, _llm = run_patch(
        failing_v0,
        make_diagnosis("memory", case_ids=["t1", "t2"], count=6),
        answers=[proposals],
    )

    written = failing_v0.payloads("memory_written")
    by_kind = {w["kind"]: w for w in written}
    assert by_kind["rule"]["evidence_case_ids"] == ["t1"]
    assert by_kind["tool_note"]["evidence_case_ids"] == ["t2"]
    # The episode summarizes the group, so it legitimately cites all of it.
    assert by_kind["episode"]["evidence_case_ids"] == ["t1", "t2"]
    assert candidate == 1


def test_an_overlapping_case_id_does_not_borrow_another_cases_evidence(
    workspace: Workspace,
):
    """Group `{t1, t2}`, evidence naming `t10`. Substring matching would
    record the note as evidenced by `t1`; whole-token matching drops it,
    because `t10` is not in the group."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False] * 3, "t10": [False] * 3},
        signatures={"t1": "wrong_output", "t2": "wrong_output", "t10": "other"},
    )
    proposals = reflection_answer(
        tool_notes=[
            {
                "tool": "lookup_ticket",
                "note": "It takes the bare ticket id.",
                "evidence": "t10 called the tool incorrectly",
            }
        ]
    )
    run_patch(
        workspace,
        make_diagnosis("memory", case_ids=["t1", "t2"], count=6),
        answers=[proposals],
    )

    # Nothing survived reflection's filter, so the attempt fell back to prompt.
    assert workspace.only("fix_proposed")["lever"] == "prompt"
    assert workspace.payloads("memory_written") == []


# -- tools lever --------------------------------------------------------


def test_tools_lever_edits_the_package_copy_and_leaves_the_shared_toolbox_alone(
    failing_v0: Workspace,
):
    """Section K: the improver rewrites the agent's *own* copy of a tool.
    `backend/toolbox/` is shared by every agent and is never touched."""
    import backend.toolbox

    toolbox_dir = Path(backend.toolbox.__file__).resolve().parent
    before = {p: p.read_bytes() for p in toolbox_dir.rglob("*.py")}

    candidate, _llm = run_patch(
        failing_v0,
        make_diagnosis("tools", metric_signal="invalid-parameter errors on 30% of calls"),
    )

    patched = (failing_v0.package_dir(candidate) / "tools" / "lookup.py").read_text(
        encoding="utf-8"
    )
    original = (failing_v0.package_dir(0) / "tools" / "lookup.py").read_text(encoding="utf-8")
    # `pprint` rewraps the TOOL literal, so the lesson is asserted on the
    # loaded description in the next test; here only that the edit landed.
    assert "lever=tools" in patched
    assert "run(input: dict)" in patched  # the rest of the module survived
    # v0's own copy is untouched evidence, and so is the shared toolbox.
    assert "lever=tools" not in original
    assert all(p.read_bytes() == blob for p, blob in before.items())


def test_the_patched_tool_module_is_still_importable_and_keeps_its_schema(
    failing_v0: Workspace,
):
    """A rewritten description that broke `TOOL` would fail the whole
    candidate at load time, which the gate would report as `error` rather
    than as the tools fix it is. Assert the module still parses."""
    from backend.runtime.package import load_from_dir

    candidate, _llm = run_patch(
        failing_v0, make_diagnosis("tools", metric_signal="redundant calls 4.2/task")
    )
    package = load_from_dir(
        failing_v0.package_dir(candidate), agent_id=failing_v0.agent_id, version=candidate
    )
    spec = next(t for t in package.tool_specs() if t["name"] == "lookup_ticket")
    assert spec["input_schema"]["required"] == ["ticket_id"]
    assert spec["description"].startswith("Return the stored record for a ticket id")
    assert "Lesson from v1 (improver, lever=tools)" in spec["description"]
    assert "Record that duplicate invoice charges are billing at p1." in spec["description"]


def test_tools_falls_back_to_prompt_when_no_target_tool_can_be_inferred(
    workspace: Workspace,
):
    """No transcripts, no tool-name match in the diagnosis text, and more
    than one tool in the package: there is nothing to rewrite, so the attempt
    degrades to a prompt edit instead of failing."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3},
        signatures={"t1": "wrong_output"},
        tools_called={"t1": []},
    )
    _candidate, _llm = run_patch(
        workspace, make_diagnosis("tools", metric_signal="tool errors 12%")
    )
    assert workspace.only("fix_proposed")["lever"] == "prompt"


# -- prompt and orchestration levers ------------------------------------


def test_prompt_lever_appends_a_targeted_section_rather_than_rewriting(
    failing_v0: Workspace,
):
    candidate, _llm = run_patch(failing_v0, make_diagnosis("prompt"))
    before = (failing_v0.package_dir(0) / "prompt.md").read_text(encoding="utf-8")
    after = (failing_v0.package_dir(candidate) / "prompt.md").read_text(encoding="utf-8")

    assert after.startswith(before.rstrip())
    assert "## Lesson (v1)" in after
    assert "Record that duplicate invoice charges are billing at p1." in after


def test_orchestration_lever_flips_the_mode_and_records_why(failing_v0: Workspace):
    candidate, _llm = run_patch(failing_v0, make_diagnosis("orchestration"))
    config = yaml.safe_load(
        (failing_v0.package_dir(candidate) / "agent.yaml").read_text(encoding="utf-8")
    )

    assert config["orchestration"] == "planner_worker"
    assert config["orchestration_reason"] == (
        "Record that duplicate invoice charges are billing at p1."
    )
    assert config["version"] == candidate


def test_an_unknown_lever_is_refused(failing_v0: Workspace):
    with pytest.raises(PatchError, match="unknown lever"):
        run_patch(failing_v0, make_diagnosis("vibes"))


# -- the patch boundary validates too -----------------------------------


def test_patch_refuses_a_tools_diagnosis_with_no_metric_signal(failing_v0: Workspace):
    """`diagnose` coerces an invalid answer down to `prompt`, but a caller
    reaching `patch()` directly must not be able to bypass section K."""
    with pytest.raises(PatchError, match="no metric_signal"):
        run_patch(failing_v0, make_diagnosis("tools", metric_signal=None))
    assert failing_v0.payloads("fix_proposed") == []
    assert not failing_v0.package_dir(1).exists()


def test_patch_refuses_a_metric_signal_that_contradicts_the_observation(
    failing_v0: Workspace,
):
    diagnosis = make_diagnosis(
        "tools", metric_signal="lookup_ticket: invalid-parameter errors on 30% of calls"
    )
    diagnosis.observed_tool_usage = {
        "lookup_ticket": {"calls": 3.0, "errors": 0.0, "redundant": 0.0}
    }
    with pytest.raises(PatchError, match="errors=0"):
        run_patch(failing_v0, diagnosis)


def test_patch_refuses_a_drift_group_diagnosed_as_memory(failing_v0: Workspace):
    with pytest.raises(PatchError, match="must resolve to"):
        run_patch(failing_v0, make_diagnosis("memory", signature="drift:loop"))


def test_a_tools_fix_records_the_observation_next_to_the_claim(failing_v0: Workspace):
    """Section 0: the ledger holds the harness's measurement alongside the
    model's sentence about it, so the card can be checked later."""
    diagnosis = make_diagnosis("tools", metric_signal="lookup_ticket: 1.0 calls/failing trial")
    diagnosis.observed_tool_usage = {
        "lookup_ticket": {"calls": 1.0, "errors": 0.0, "redundant": 0.0}
    }
    run_patch(failing_v0, diagnosis)

    proposed = failing_v0.only("fix_proposed")
    assert proposed["extra"] == {
        "observed_tool_usage": {"lookup_ticket": {"calls": 1.0, "errors": 0.0, "redundant": 0.0}}
    }


def test_the_other_levers_carry_no_observation(failing_v0: Workspace):
    run_patch(failing_v0, make_diagnosis("prompt"))
    assert failing_v0.only("fix_proposed")["extra"] == {}
