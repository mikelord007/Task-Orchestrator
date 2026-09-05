"""Tests for `scripts/build_github_cases.py`.

Only the offline, network-free half is exercised: label derivation, duplicate
parsing, tagging, the temporal split, and the guarantee that `cases.jsonl` is
derivable from the committed raw snapshots alone. Nothing here makes a request.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_github_cases", REPO_ROOT / "scripts" / "build_github_cases.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load_module()

SNAPSHOT_DIR = REPO_ROOT / "fixtures" / "github_triage" / "issues"
CASES_PATH = REPO_ROOT / "evaluators" / "github_triage" / "cases.jsonl"


def _issue(**overrides) -> dict:
    issue = {
        "number": 4321,
        "title": "Daemon crashes on start",
        "body": "x" * 500,
        "created_at": "2026-08-25T10:00:00Z",
        "user": {"login": "someone"},
        "assignee": None,
        "labels": [{"name": "bug"}, {"name": "comp/daemon"}, {"name": "P1"}],
    }
    issue.update(overrides)
    return issue


# ------------------------------------------------------------------ label parsing


def test_labels_split_into_plain_component_and_priority():
    names = builder.label_names(_issue())
    assert builder.plain_labels(names) == ["bug"]
    assert builder.components(names) == ["comp/daemon"]
    assert builder.priority(names) == "P1"


def test_absent_priority_label_becomes_none():
    assert builder.priority(["bug", "comp/cli"]) == "none"


def test_components_are_sorted_and_multiple_are_kept():
    names = ["comp/desktop", "bug", "comp/cli"]
    assert builder.components(names) == ["comp/cli", "comp/desktop"]


def test_input_never_leaks_the_answer():
    case = builder.build_case("o/r", _issue(assignee={"login": "maintainer"}), [])
    assert set(case["input"]) == {"issue_number", "title", "body", "author", "created_at", "repo"}
    for leak in ("labels", "component", "priority", "assignee", "state", "duplicate_of"):
        assert leak not in case["input"]
    assert case["expected"]["assignee"] == "maintainer"


# --------------------------------------------------------------- duplicate parsing


@pytest.mark.parametrize(
    "body",
    [
        "duplicate of #123",
        "dup of #123",
        "Closing as duplicate of #123",
        "closed as dup of #123",
        "Thanks -- this is a DUPLICATE OF #123, see there.",
    ],
)
def test_duplicate_phrasings_are_parsed(body):
    assert builder.parse_duplicate_of([{"body": body}]) == 123


@pytest.mark.parametrize(
    "body", ["no duplicates here", "see #123", "duplicate of the other one", ""]
)
def test_non_duplicate_comments_yield_none(body):
    assert builder.parse_duplicate_of([{"body": body}]) is None


def test_duplicate_search_skips_earlier_comments_without_a_match():
    comments = [{"body": "can you attach a log?"}, {"body": "dup of #99"}]
    assert builder.parse_duplicate_of(comments) == 99


# ------------------------------------------------------------------------- tagging


def test_hard_case_tags_are_derived_from_the_issue_and_the_answer():
    issue = _issue(body="PowerShell hangs on ConPTY " + "x" * 40)
    expected = {
        "labels": ["bug"],
        "component": ["comp/cli", "comp/daemon"],
        "priority": "none",
        "assignee": "maintainer",
        "duplicate_of": 7,
    }
    tags = builder.build_tags(issue, expected)
    assert set(tags) >= {
        "comp:comp/cli",
        "comp:comp/daemon",
        "prio:none",
        "multi-component",
        "no-priority",
        "duplicate",
        "assigned",
        "windows",
        "short-body",
    }
    assert "long-body" not in tags


def test_body_length_tags_are_mutually_exclusive():
    expected = {"labels": [], "component": ["comp/cli"], "priority": "P2", "assignee": None}
    expected["duplicate_of"] = None
    long_tags = builder.build_tags(_issue(body="y" * 4000), expected)
    assert "long-body" in long_tags and "short-body" not in long_tags
    mid_tags = builder.build_tags(_issue(body="y" * 1000), expected)
    assert "long-body" not in mid_tags and "short-body" not in mid_tags


# ------------------------------------------------------------------------ negatives


def test_reference_output_is_a_copy_of_expected():
    case = builder.build_case("o/r", _issue(), [])
    assert case["reference_output"] == case["expected"]
    assert case["reference_output"] is not case["expected"]


def test_negative_candidate_requires_both_no_priority_and_urgent_language():
    urgent_no_prio = {
        "id": "gh-1",
        "input": {"title": "App crashes on launch", "body": "x"},
        "expected": {"priority": "none"},
    }
    urgent_with_prio = {
        "id": "gh-2",
        "input": {"title": "App crashes on launch", "body": "x"},
        "expected": {"priority": "P1"},
    }
    calm_no_prio = {
        "id": "gh-3",
        "input": {"title": "Question about the docs", "body": "x"},
        "expected": {"priority": "none"},
    }
    assert builder.is_negative_candidate(urgent_no_prio) is True
    assert builder.is_negative_candidate(urgent_with_prio) is False
    assert builder.is_negative_candidate(calm_no_prio) is False


def test_apply_negative_tags_caps_at_the_target_oldest_first():
    cases = [
        {
            "id": f"gh-{i}",
            "input": {
                "title": "critical bug",
                "body": "x",
                "created_at": f"2026-08-{i + 1:02d}T00:00:00Z",
            },
            "expected": {"priority": "none"},
            "tags": [],
        }
        for i in range(builder.NEGATIVE_TARGET + 5)
    ]
    tagged = builder.apply_negative_tags(cases)
    negative_ids = {c["id"] for c in tagged if "negative:no_priority" in c["tags"]}
    assert len(negative_ids) == builder.NEGATIVE_TARGET
    assert negative_ids == {f"gh-{i}" for i in range(builder.NEGATIVE_TARGET)}


def test_the_committed_corpus_has_the_target_number_of_negatives():
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()]
    negatives = [c for c in cases if any(t.startswith("negative:") for t in c["tags"])]
    assert len(negatives) == builder.NEGATIVE_TARGET


# ------------------------------------------------------------------ temporal split


def test_temporal_split_puts_the_oldest_70_percent_in_train():
    cases = [
        {
            "id": f"gh-{i}",
            "split": "train",
            "input": {"issue_number": i, "created_at": f"2026-08-{i + 1:02d}T00:00:00Z"},
        }
        for i in range(10)
    ]
    split = builder.apply_temporal_split(cases)
    assert [c["split"] for c in split] == ["train"] * 7 + ["holdout"] * 3
    newest_train = max(c["input"]["created_at"] for c in split if c["split"] == "train")
    oldest_holdout = min(c["input"]["created_at"] for c in split if c["split"] == "holdout")
    assert newest_train < oldest_holdout


# ----------------------------------------------------------------- reproducibility


def test_every_case_has_a_committed_raw_snapshot():
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()]
    assert cases
    for case in cases:
        snapshot = SNAPSHOT_DIR / f"{case['input']['issue_number']}.json"
        assert snapshot.exists(), case["id"]


def test_cases_jsonl_is_reproducible_from_the_snapshots_offline():
    """No token, no network: the committed snapshots alone rebuild the corpus."""
    rebuilt = builder.cases_from_snapshots(SNAPSHOT_DIR)
    committed = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()]
    assert rebuilt == committed
