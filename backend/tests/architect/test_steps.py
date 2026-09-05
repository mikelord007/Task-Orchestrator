from __future__ import annotations

import json

import pytest

from backend.architect import steps
from backend.architect.evaluator_reader import read_evaluator


@pytest.fixture
def evaluator(evaluator_dir):
    return read_evaluator("widget_triage", root=evaluator_dir)


# ------------------------------------------------------------- filter_known_tools


def test_filter_known_tools_keeps_only_toolbox_names():
    assert steps.filter_known_tools(["json_validate", "not_a_tool", "date_parse"]) == [
        "json_validate",
        "date_parse",
    ]


def test_filter_known_tools_raises_when_nothing_matches():
    with pytest.raises(steps.ArchitectStepError):
        steps.filter_known_tools(["not_a_tool"])


# ------------------------------------------------------------- choose_orchestration


def test_choose_orchestration_parses_mode_and_reason(evaluator, make_complete):
    complete, fake = make_complete([json.dumps({"mode": "single", "reason": "One call suffices."})])
    result, response = steps.choose_orchestration("goal", "domain", evaluator, complete, "strong")
    assert result == {"mode": "single", "reason": "One call suffices."}
    assert isinstance(response["cost_usd"], float)
    assert fake.call_count == 1


def test_choose_orchestration_retries_once_on_bad_json_then_succeeds(evaluator, make_complete):
    complete, fake = make_complete(
        ["not json", json.dumps({"mode": "planner_worker", "reason": "Needs planning."})]
    )
    result, _ = steps.choose_orchestration("goal", "domain", evaluator, complete, "strong")
    assert result["mode"] == "planner_worker"
    assert fake.call_count == 2


def test_choose_orchestration_raises_after_a_failed_retry(evaluator, make_complete):
    complete, _fake = make_complete(["not json", "still not json"])
    with pytest.raises(steps.ArchitectStepError):
        steps.choose_orchestration("goal", "domain", evaluator, complete, "strong")


def test_choose_orchestration_rejects_an_unknown_mode(evaluator, make_complete):
    complete, _fake = make_complete(
        [json.dumps({"mode": "yolo", "reason": "x"}), json.dumps({"mode": "yolo", "reason": "x"})]
    )
    with pytest.raises(steps.ArchitectStepError):
        steps.choose_orchestration("goal", "domain", evaluator, complete, "strong")


# ------------------------------------------------------------------- draft_prompt


def test_draft_prompt_returns_the_raw_text_when_it_already_mentions_json_and_keys(
    evaluator, make_complete
):
    text = "Answer with JSON containing labels, component and priority."
    complete, _fake = make_complete([text])
    orchestration = {"mode": "single", "reason": "r"}
    result, _ = steps.draft_prompt("goal", "domain", evaluator, orchestration, complete, "strong")
    assert result == text


def test_draft_prompt_appends_an_output_format_footer_when_missing(evaluator, make_complete):
    complete, _fake = make_complete(["Be a good triage agent."])
    orchestration = {"mode": "single", "reason": "r"}
    result, _ = steps.draft_prompt("goal", "domain", evaluator, orchestration, complete, "strong")
    assert "Output format" in result
    assert "labels" in result and "component" in result


def test_draft_prompt_rejects_empty_text(evaluator, make_complete):
    complete, _fake = make_complete(["   "])
    orchestration = {"mode": "single", "reason": "r"}
    with pytest.raises(steps.ArchitectStepError):
        steps.draft_prompt("goal", "domain", evaluator, orchestration, complete, "strong")


# ------------------------------------------------------------------- select_tools


def test_select_tools_returns_the_requested_subset(evaluator, make_complete):
    complete, _fake = make_complete([json.dumps({"tools": ["json_validate"], "glue_tool": None})])
    result, _ = steps.select_tools(
        "goal", "domain", evaluator, ["json_validate", "date_parse"], complete, "strong"
    )
    assert result == {"tools": ["json_validate"], "glue_tool": None}


def test_select_tools_falls_back_to_the_full_allow_list_when_the_model_picks_nothing_usable(
    evaluator, make_complete
):
    complete, _fake = make_complete([json.dumps({"tools": ["not_allowed"], "glue_tool": None})])
    result, _ = steps.select_tools(
        "goal", "domain", evaluator, ["json_validate", "date_parse"], complete, "strong"
    )
    assert result["tools"] == ["json_validate", "date_parse"]


def test_select_tools_raises_when_the_allow_list_is_empty(evaluator, make_complete):
    complete, _fake = make_complete([])
    with pytest.raises(steps.ArchitectStepError):
        steps.select_tools("goal", "domain", evaluator, [], complete, "strong")


VALID_GLUE_TOOL = {
    "name": "combine_labels",
    "description": "Combines two label sets. Returns JSON. Does not call the network.",
    "code": (
        "TOOL = {'name': 'combine_labels', 'description': 'd', "
        "'input_schema': {'type': 'object', 'properties': {}}}\n\n"
        "def run(input: dict) -> str:\n    return '{}'\n"
    ),
    "test_code": "def test_placeholder():\n    assert True\n",
}


def test_select_tools_accepts_a_syntactically_valid_glue_tool(evaluator, make_complete):
    complete, _fake = make_complete(
        [json.dumps({"tools": ["json_validate"], "glue_tool": VALID_GLUE_TOOL})]
    )
    result, _ = steps.select_tools(
        "goal", "domain", evaluator, ["json_validate"], complete, "strong"
    )
    assert result["glue_tool"]["name"] == "combine_labels"


def test_select_tools_drops_a_glue_tool_with_invalid_python(evaluator, make_complete):
    bad = {**VALID_GLUE_TOOL, "code": "def broken(:\n"}
    complete, _fake = make_complete([json.dumps({"tools": ["json_validate"], "glue_tool": bad})])
    result, _ = steps.select_tools(
        "goal", "domain", evaluator, ["json_validate"], complete, "strong"
    )
    assert result["glue_tool"] is None


def test_select_tools_drops_a_glue_tool_that_shadows_an_allowed_or_toolbox_name(
    evaluator, make_complete
):
    shadowing = {**VALID_GLUE_TOOL, "name": "json_validate"}
    complete, _fake = make_complete([json.dumps({"tools": ["date_parse"], "glue_tool": shadowing})])
    result, _ = steps.select_tools("goal", "domain", evaluator, ["date_parse"], complete, "strong")
    assert result["glue_tool"] is None


def test_select_tools_drops_a_glue_tool_missing_required_fields(evaluator, make_complete):
    incomplete = {"name": "x"}
    complete, _fake = make_complete(
        [json.dumps({"tools": ["date_parse"], "glue_tool": incomplete})]
    )
    result, _ = steps.select_tools("goal", "domain", evaluator, ["date_parse"], complete, "strong")
    assert result["glue_tool"] is None


# ----------------------------------------------------------------- apply_playbook


def test_apply_playbook_returns_revised_prompt_and_applied_ids(make_complete):
    lessons = [{"id": "l1", "domain_tags": ["x"]}, {"id": "l2", "domain_tags": ["y"]}]
    complete, _fake = make_complete(
        [json.dumps({"prompt": "revised prompt text", "applied_lesson_ids": ["l1"]})]
    )
    result, _ = steps.apply_playbook("goal", "domain", "original", lessons, complete, "strong")
    assert result == {"prompt": "revised prompt text", "applied_lessons": ["l1"]}


def test_apply_playbook_filters_out_unknown_lesson_ids(make_complete):
    lessons = [{"id": "l1", "domain_tags": []}]
    complete, _fake = make_complete(
        [json.dumps({"prompt": "revised", "applied_lesson_ids": ["l1", "does-not-exist"]})]
    )
    result, _ = steps.apply_playbook("goal", "domain", "original", lessons, complete, "strong")
    assert result["applied_lessons"] == ["l1"]


def test_apply_playbook_keeps_the_original_prompt_when_the_model_returns_nothing_usable(
    make_complete,
):
    complete, _fake = make_complete([json.dumps({"prompt": "", "applied_lesson_ids": ["l1"]})])
    result, _ = steps.apply_playbook("goal", "domain", "original", [], complete, "strong")
    assert result == {"prompt": "original", "applied_lessons": []}
