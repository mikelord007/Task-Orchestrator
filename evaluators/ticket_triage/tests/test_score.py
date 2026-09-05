"""Unit tests for the `ticket_triage` scorer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

EVALUATOR_DIR = Path(__file__).resolve().parents[1]


def _load_score():
    spec = importlib.util.spec_from_file_location(
        "ticket_triage_score", EVALUATOR_DIR / "score.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.score


score = _load_score()

EXPECTED = {"category": "bug", "priority": "p1", "needs_human": True}
THIRD = 1 / 3


def test_all_three_fields_match():
    result = score(EXPECTED, dict(EXPECTED))
    assert result == {"passed": True, "score": 1.0, "notes": "ok"}


def test_one_field_wrong_fails_and_scores_two_thirds():
    result = score(EXPECTED, {"category": "feature", "priority": "p1", "needs_human": True})
    assert result["passed"] is False
    assert result["score"] == pytest.approx(2 / 3)
    assert result["notes"] == "category_mismatch:bug->feature"


def test_two_fields_wrong_scores_one_third_and_lists_both_sorted():
    result = score(EXPECTED, {"category": "billing", "priority": "p3", "needs_human": True})
    assert result["score"] == pytest.approx(THIRD)
    assert result["notes"] == "category_mismatch:bug->billing;priority_mismatch:p1->p3"


def test_all_three_wrong_scores_zero():
    result = score(EXPECTED, {"category": "other", "priority": "p3", "needs_human": False})
    assert result["passed"] is False
    assert result["score"] == pytest.approx(0.0)
    assert result["notes"] == (
        "category_mismatch:bug->other;"
        "needs_human_mismatch:true->false;"
        "priority_mismatch:p1->p3"
    )


def test_needs_human_mismatch_alone():
    result = score(EXPECTED, {"category": "bug", "priority": "p1", "needs_human": False})
    assert result["notes"] == "needs_human_mismatch:true->false"
    assert result["score"] == pytest.approx(2 / 3)


def test_absent_fields_are_reported_as_missing():
    result = score(EXPECTED, {"category": "bug"})
    assert result["passed"] is False
    assert result["notes"] == (
        "needs_human_mismatch:true->missing;priority_mismatch:p1->missing"
    )
    assert result["score"] == pytest.approx(THIRD)


def test_stringly_typed_needs_human_is_accepted():
    for truthy in ("true", "True", " YES ", "1", 1):
        assert score(EXPECTED, {"category": "bug", "priority": "p1", "needs_human": truthy})[
            "passed"
        ] is True
    falsy_expected = {"category": "bug", "priority": "p1", "needs_human": False}
    for falsy in ("false", "No", "0", 0):
        assert score(
            falsy_expected, {"category": "bug", "priority": "p1", "needs_human": falsy}
        )["passed"] is True


def test_unparseable_needs_human_is_missing_not_false():
    result = score(
        {"category": "bug", "priority": "p1", "needs_human": False},
        {"category": "bug", "priority": "p1", "needs_human": "maybe"},
    )
    assert result["notes"] == "needs_human_mismatch:false->missing"


def test_category_and_priority_are_case_and_whitespace_insensitive():
    result = score(EXPECTED, {"category": " BUG ", "priority": "P1", "needs_human": True})
    assert result == {"passed": True, "score": 1.0, "notes": "ok"}


@pytest.mark.parametrize("actual", [None, "bug", 7, ["bug"]])
def test_non_dict_actual_is_no_output(actual):
    assert score(EXPECTED, actual) == {"passed": False, "score": 0.0, "notes": "no_output"}


def _cases():
    path = EVALUATOR_DIR / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_committed_case_self_scores_perfectly():
    cases = _cases()
    assert cases, "cases.jsonl is empty"
    for case in cases:
        assert score(case["expected"], case["expected"]) == {
            "passed": True,
            "score": 1.0,
            "notes": "ok",
        }, case["id"]


def test_committed_expected_values_are_inside_the_declared_vocabularies():
    for case in _cases():
        expected = case["expected"]
        assert expected["category"] in {"billing", "bug", "feature", "account", "other"}
        assert expected["priority"] in {"p0", "p1", "p2", "p3"}
        assert isinstance(expected["needs_human"], bool)


def test_empty_actual_scores_zero_on_every_committed_case():
    results = [score(case["expected"], {}) for case in _cases()]
    assert not any(r["passed"] for r in results)
    assert max(r["score"] for r in results) == pytest.approx(0.0)
