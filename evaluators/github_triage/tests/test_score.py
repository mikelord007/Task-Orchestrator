"""Unit tests for the `github_triage` scorer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

EVALUATOR_DIR = Path(__file__).resolve().parents[1]


def _load_score():
    spec = importlib.util.spec_from_file_location(
        "github_triage_score", EVALUATOR_DIR / "score.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.score


score = _load_score()

EXPECTED = {
    "labels": ["bug", "needs-triage"],
    "component": ["comp/daemon"],
    "priority": "P1",
    "assignee": "illegalcall",
    "duplicate_of": None,
}


def test_exact_match_passes_with_full_score():
    result = score(EXPECTED, dict(EXPECTED))
    assert result["passed"] is True
    assert result["score"] == pytest.approx(1.0)
    assert result["notes"] == "ok"


def test_partial_label_f1_below_threshold_fails_and_names_both_sides():
    actual = {"labels": ["enhancement"], "component": ["comp/daemon"], "priority": "P1"}
    result = score(EXPECTED, actual)
    # F1 = 0 (no overlap): 0.5*0 + 0.3*1 + 0.2*1
    assert result["passed"] is False
    assert result["score"] == pytest.approx(0.5)
    assert result["notes"] == "extra_label:enhancement;missing_label:bug;missing_label:needs-triage"


def test_partial_label_f1_can_still_pass_at_the_threshold():
    expected = {"labels": ["bug", "cloud", "enhancement", "blocked"], "component": ["comp/cli"]}
    actual = {"labels": ["bug", "cloud", "enhancement", "blocked", "documentation"]}
    actual["component"] = ["comp/cli"]
    actual["priority"] = "none"
    result = score(expected, actual)
    # precision 4/5, recall 4/4 -> F1 = 8/9 = 0.888... >= 0.8
    assert result["passed"] is True
    assert result["score"] == pytest.approx(0.5 * (8 / 9) + 0.3 + 0.2)
    assert result["notes"] == "extra_label:documentation"


def test_component_mismatch_fails_even_with_perfect_labels():
    actual = {"labels": ["bug", "needs-triage"], "component": ["comp/desktop"], "priority": "P1"}
    result = score(EXPECTED, actual)
    assert result["passed"] is False
    assert result["notes"] == "component_mismatch"
    assert result["score"] == pytest.approx(0.5 + 0.2)


def test_component_accepts_a_bare_string_as_a_one_element_list():
    actual = {"labels": ["bug", "needs-triage"], "component": "comp/daemon", "priority": "p1"}
    result = score(EXPECTED, actual)
    assert result["passed"] is True
    assert result["score"] == pytest.approx(1.0)


def test_multi_component_requires_set_equality():
    expected = {"labels": [], "component": ["comp/cli", "comp/daemon"], "priority": "none"}
    result = score(expected, {"labels": [], "component": ["comp/daemon"], "priority": "none"})
    assert result["passed"] is False
    assert result["notes"] == "component_mismatch"


def test_missing_priority_in_actual_is_treated_as_none():
    expected = {"labels": ["bug"], "component": ["comp/cli"], "priority": "none"}
    result = score(expected, {"labels": ["bug"], "component": ["comp/cli"]})
    assert result["passed"] is True
    assert result["score"] == pytest.approx(1.0)
    assert result["notes"] == "ok"


def test_missing_priority_against_a_real_priority_is_a_mismatch():
    actual = {"labels": ["bug", "needs-triage"], "component": ["comp/daemon"]}
    result = score(EXPECTED, actual)
    assert result["passed"] is True  # passing does not require priority
    assert result["notes"] == "priority_mismatch"
    assert result["score"] == pytest.approx(0.8)


def test_both_label_sets_empty_scores_one():
    expected = {"labels": [], "component": ["comp/docs-site"], "priority": "none"}
    result = score(expected, {"labels": [], "component": ["comp/docs-site"], "priority": "none"})
    assert result["score"] == pytest.approx(1.0)
    assert result["passed"] is True


def test_labels_omitted_by_the_agent_when_labels_were_expected():
    result = score(EXPECTED, {"component": ["comp/daemon"], "priority": "P1"})
    assert result["passed"] is False
    assert result["notes"] == "missing_label:bug;missing_label:needs-triage"


@pytest.mark.parametrize("actual", [None, "some text", 42, ["bug"]])
def test_non_dict_actual_is_no_output(actual):
    result = score(EXPECTED, actual)
    assert result == {"passed": False, "score": 0.0, "notes": "no_output"}


def test_scoring_is_case_and_whitespace_insensitive():
    actual = {"labels": [" Bug ", "Needs-Triage"], "component": ["COMP/Daemon"], "priority": " p1 "}
    assert score(EXPECTED, actual)["score"] == pytest.approx(1.0)


def test_every_committed_case_self_scores_perfectly():
    """The recorded ground truth must be a passing answer to its own case."""
    cases_path = EVALUATOR_DIR / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
    assert cases, "cases.jsonl is empty"
    for case in cases:
        result = score(case["expected"], case["expected"])
        assert result["passed"] is True, case["id"]
        assert result["score"] == pytest.approx(1.0), case["id"]


def test_empty_actual_scores_near_zero_on_every_committed_case():
    cases_path = EVALUATOR_DIR / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
    results = [score(case["expected"], {}) for case in cases]
    assert not any(r["passed"] for r in results)
    assert sum(r["score"] for r in results) / len(results) < 0.15
