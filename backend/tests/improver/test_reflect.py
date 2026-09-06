"""Reflection (PLAN_ADDENDUM.md sections E and 0). FakeLLM only, no network.

Section 0 is the constraint the whole step exists under: the grade is given,
never asked for. Two things follow, and both are asserted here.

* The prompt carries section E's mandated sentence **verbatim**. It is
  written out as a literal in this file rather than imported from
  `reflect.MANDATE`, so an edit to the constant that changes the wording
  fails here instead of quietly shipping.
* A proposal may only cite evidence from the group it was reflected from.
  A rule whose evidence is a case the model never saw is not a lesson, it is
  a guess -- and one that would then be injected into the next version's
  memory as if it had been observed.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.improver.reflect import MAX_RULES, MAX_TOOL_NOTES, cited_case_ids, reflect
from backend.tests.improver.conftest import JsonLLM, Workspace, reflection_answer
from contracts.events import FailingGroup

#: PLAN_ADDENDUM.md section E, spelled out. Do not replace with the constant.
MANDATED_SENTENCE = (
    "Do not evaluate your own performance; the grade is given. Explain the "
    "discrepancy using only the transcript and tool data provided."
)

GROUP = FailingGroup(signature="wrong_output", tag="billing", case_ids=["t1", "t2"], count=4)

ONE_RULE = reflection_answer(
    rules=[
        {
            "rule": "A duplicated invoice charge is billing at p1.",
            "scope_keywords": ["invoice", "charge"],
            "evidence_case_ids": ["t1"],
        }
    ]
)


def run_reflect(
    workspace: Workspace,
    answers: list[Any],
    *,
    group: FailingGroup = GROUP,
    version: int = 0,
) -> tuple[list[Any], JsonLLM]:
    llm = JsonLLM(answers)
    proposals = reflect(
        workspace.agent_id,
        version,
        group,
        conn=workspace.conn,
        root=workspace.root,
        complete=llm,
    )
    return proposals, llm


@pytest.fixture
def failing_v0(workspace: Workspace) -> Workspace:
    """t1 and t2 fail every trial; t3 passes. The group is {t1, t2}."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False] * 3, "t3": [True] * 3},
        signatures={"t1": "wrong_output", "t2": "wrong_output"},
        notes={
            "t1": "category mismatch: got bug, want billing",
            "t2": "priority mismatch: got p2, want p0",
        },
    )
    return workspace


# -- the mandated sentence ----------------------------------------------


def test_the_reflection_prompt_contains_the_mandated_sentence_verbatim(
    failing_v0: Workspace,
):
    _proposals, llm = run_reflect(failing_v0, [ONE_RULE])

    assert llm.call_count == 1
    system = llm.prompts[0][0]
    assert system["role"] == "system"
    assert MANDATED_SENTENCE in system["content"]


def test_the_mandate_constant_is_the_sentence_the_addendum_specifies():
    """Guards the constant itself, so a reword shows up as a failing test
    rather than as a silently weakened instruction."""
    from backend.improver.reflect import MANDATE

    assert MANDATE == MANDATED_SENTENCE


def test_the_prompt_never_asks_the_agent_how_it_did(failing_v0: Workspace):
    """Rule 2.8: observed facts, never self-reports. The grade goes *in*."""
    _proposals, llm = run_reflect(failing_v0, [ONE_RULE])
    text = llm.prompt_text(0).lower()

    assert "did you succeed" not in text
    assert "were you correct" not in text
    assert "rate your" not in text
    assert "the grade is given" in text


# -- the evidence shown -------------------------------------------------


def test_the_prompt_shows_the_harness_recorded_evidence_for_the_group(
    failing_v0: Workspace,
):
    """Transcript tool calls and returns, the grader's notes, the evaluator's
    `expected` output and the agent's actual output -- and nothing from
    outside the group."""
    _proposals, llm = run_reflect(failing_v0, [ONE_RULE])
    text = llm.prompt_text(0)

    assert "Case t1" in text and "Case t2" in text
    assert "Case t3" not in text  # t3 passed; it is not this group's evidence
    assert "CALL lookup_ticket" in text
    assert "RETURN lookup_ticket" in text
    assert "category mismatch: got bug, want billing" in text
    assert "priority mismatch: got p2, want p0" in text
    assert "invoice charged twice" in text  # the case input from cases.jsonl
    assert '"category": "billing"' in text  # the expected output
    assert "Expected output:" in text and "Agent's final output:" in text


def test_the_prompt_carries_the_graders_verdict_not_only_its_notes(
    failing_v0: Workspace,
):
    """The brief requires the grader verdict: `passed` and `score` as well as
    the notes. Reflection must be able to tell a near-miss from a total miss."""
    _proposals, llm = run_reflect(failing_v0, [ONE_RULE])
    text = llm.prompt_text(0)

    assert "Grader verdict: FAILED at score 0.00" in text
    assert "category mismatch: got bug, want billing" in text


def test_a_narrow_failure_and_a_total_one_do_not_look_identical(workspace: Workspace):
    """Same notes, different scores. Without the score in the prompt these
    two tasks are indistinguishable and invite one over-broad rule."""
    workspace.seed_run(
        0,
        {"t1": [False] * 3, "t2": [False] * 3},
        notes={"t1": "priority mismatch", "t2": "priority mismatch"},
        scores={"t1": 0.79},
    )
    _proposals, llm = run_reflect(
        workspace,
        [ONE_RULE],
        group=FailingGroup(signature="wrong_output", tag=None, case_ids=["t1", "t2"], count=6),
    )
    text = llm.prompt_text(0)

    assert "FAILED at score 0.79" in text
    assert "FAILED at score 0.00" in text


def test_a_group_with_no_readable_transcripts_makes_no_llm_call(workspace: Workspace):
    """Reflecting on nothing would invite the model to invent a lesson. Cost
    nothing and propose nothing instead."""
    workspace.seed_run(0, {"t1": [True] * 3})  # nothing failed
    proposals, llm = run_reflect(workspace, [ONE_RULE])

    assert proposals == []
    assert llm.call_count == 0


# -- evidence filtering -------------------------------------------------


def test_evidence_ids_are_filtered_down_to_the_group(failing_v0: Workspace):
    """A rule citing one in-group and one out-of-group case keeps only the
    in-group id."""
    answer = reflection_answer(
        rules=[
            {
                "rule": "Duplicate invoice charges are billing at p1.",
                "scope_keywords": ["invoice"],
                "evidence_case_ids": ["t1", "t3", "t99"],
            }
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])

    assert len(proposals) == 1
    assert proposals[0].evidence_case_ids == ["t1"]


def test_a_rule_citing_only_cases_outside_the_group_is_dropped(failing_v0: Workspace):
    """With every citation stripped there is no evidence left, so there is no
    proposal -- an unevidenced rule is never written to memory."""
    answer = reflection_answer(
        rules=[
            {
                "rule": "Everything urgent is p0.",
                "scope_keywords": ["urgent"],
                "evidence_case_ids": ["t3", "t4"],
            },
            {
                "rule": "Duplicate invoice charges are billing at p1.",
                "scope_keywords": ["invoice"],
                "evidence_case_ids": ["t2"],
            },
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])

    assert [p.rule for p in proposals] == ["Duplicate invoice charges are billing at p1."]


def test_a_rule_with_no_evidence_at_all_is_dropped(failing_v0: Workspace):
    answer = reflection_answer(
        rules=[{"rule": "Be careful.", "scope_keywords": [], "evidence_case_ids": []}]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])
    assert proposals == []


def test_a_tool_note_must_point_at_a_case_in_the_group(failing_v0: Workspace):
    """`ToolNote.evidence` is free text, but section E's "each citing
    evidence case ids from the group" applies to notes too."""
    answer = reflection_answer(
        tool_notes=[
            {
                "tool": "lookup_ticket",
                "note": "It needs the bare ticket id.",
                "evidence": "seen on t9, which is not in this group",
            },
            {
                "tool": "lookup_ticket",
                "note": "It does not classify the ticket for you.",
                "evidence": "t2 read the record and still answered from the title alone",
            },
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])

    assert len(proposals) == 1
    assert proposals[0].kind == "tool_note"
    assert proposals[0].note == "It does not classify the ticket for you."
    assert proposals[0].evidence_case_ids == ["t2"]


def test_an_id_is_only_cited_when_the_evidence_names_it_whole(failing_v0: Workspace):
    """`t1` does not appear inside `t10`. Substring matching would record a
    note about a case the model never mentioned as evidenced by `t1` -- false
    provenance on an append-only row."""
    answer = reflection_answer(
        tool_notes=[
            {
                "tool": "lookup_ticket",
                "note": "It takes the bare ticket id.",
                "evidence": "t10 called the tool incorrectly",
            }
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])
    assert proposals == []


def test_cited_case_ids_matches_whole_tokens_only():
    group = {"t1", "t2"}
    assert cited_case_ids("t10 called the tool incorrectly", group) == set()
    assert cited_case_ids("t1 called the tool incorrectly", group) == {"t1"}
    assert cited_case_ids("seen on t1 and t2, but not t10", group) == {"t1", "t2"}
    # Punctuation is a boundary; an id glued to a word is not the id.
    assert cited_case_ids("(t1), t2.", group) == {"t1", "t2"}
    assert cited_case_ids("case_t1 is unrelated", group) == set()


def test_a_rules_evidence_list_is_matched_exactly_too(failing_v0: Workspace):
    answer = reflection_answer(
        rules=[
            {
                "rule": "Everything is p0.",
                "scope_keywords": [],
                "evidence_case_ids": ["t10", "t100"],
            }
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])
    assert proposals == []


def test_an_incomplete_tool_note_is_dropped(failing_v0: Workspace):
    answer = reflection_answer(
        tool_notes=[
            {"tool": "lookup_ticket", "note": "", "evidence": "t1"},
            {"tool": "", "note": "something", "evidence": "t1"},
            {"tool": "lookup_ticket", "note": "something", "evidence": ""},
        ]
    )
    proposals, _llm = run_reflect(failing_v0, [answer])
    assert proposals == []


# -- caps ---------------------------------------------------------------


def test_proposals_are_capped_at_three_rules_and_two_tool_notes(failing_v0: Workspace):
    answer = reflection_answer(
        rules=[
            {
                "rule": f"Rule number {i}.",
                "scope_keywords": ["x"],
                "evidence_case_ids": ["t1"],
            }
            for i in range(6)
        ],
        tool_notes=[
            {"tool": "lookup_ticket", "note": f"Note {i}.", "evidence": "on t1"} for i in range(5)
        ],
    )
    proposals, _llm = run_reflect(failing_v0, [answer])

    rules = [p for p in proposals if p.kind == "rule"]
    notes = [p for p in proposals if p.kind == "tool_note"]
    assert len(rules) == MAX_RULES == 3
    assert len(notes) == MAX_TOOL_NOTES == 2
    # The cap keeps the first ones, not an arbitrary subset.
    assert [p.rule for p in rules] == ["Rule number 0.", "Rule number 1.", "Rule number 2."]


# -- one call, and what happens when it misbehaves ----------------------


def test_one_strong_call_per_group(failing_v0: Workspace):
    """Section E: one STRONG call per failure group, not one per case."""
    from backend import llm as llm_module

    _proposals, llm = run_reflect(failing_v0, [ONE_RULE])
    assert llm.call_count == 1
    assert llm.models == [llm_module.MODEL_STRONG]


def test_prose_around_the_json_is_retried_once_and_then_parsed(failing_v0: Workspace):
    """The model wrapping its answer in a code fence is not a failed
    reflection -- `complete_json` retries once with a blunt instruction."""
    import json

    proposals, llm = run_reflect(
        failing_v0,
        ["Sure! Here is my analysis.", f"```json\n{json.dumps(ONE_RULE)}\n```"],
    )

    assert llm.call_count == 2
    assert "No other text, no code fences" in str(llm.prompts[1][-1]["content"])
    assert [p.rule for p in proposals] == ["A duplicated invoice charge is billing at p1."]


def test_a_model_that_never_returns_json_proposes_nothing(failing_v0: Workspace):
    """Two strikes and the step yields nothing rather than half a lesson."""
    proposals, llm = run_reflect(failing_v0, ["not json", "still not json"])

    assert proposals == []
    assert llm.call_count == 2


def test_junk_entries_in_a_valid_response_are_skipped_not_fatal(failing_v0: Workspace):
    proposals, _llm = run_reflect(
        failing_v0,
        [
            {
                "rules": ["a bare string, not an object", None, ONE_RULE["rules"][0]],
                "tool_notes": "not a list of notes",
            }
        ],
    )
    assert [p.rule for p in proposals] == ["A duplicated invoice charge is billing at p1."]
