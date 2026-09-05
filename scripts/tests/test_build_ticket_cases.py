"""Tests for `scripts/build_ticket_cases.py` — determinism and the split.

The corpus is committed, so the value here is guarding the claim the README makes:
regenerating produces exactly what is on disk, and the split is stratified.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = REPO_ROOT / "evaluators" / "ticket_triage" / "cases.jsonl"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "tickets"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_ticket_cases", REPO_ROOT / "scripts" / "build_ticket_cases.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load_module()


def _committed() -> list[dict]:
    return [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()]


def test_generation_is_deterministic():
    assert builder.build_all() == builder.build_all()


def test_the_committed_corpus_matches_a_fresh_generation():
    """`cases.jsonl` is derived, never hand-patched; edits go in the generator."""
    assert builder.apply_stratified_split(builder.build_all()) == _committed()


def test_every_case_has_a_fixture_file_and_they_agree():
    for case in _committed():
        path = FIXTURE_DIR / f"{case['id']}.json"
        assert path.exists(), case["id"]
        assert json.loads(path.read_text(encoding="utf-8")) == case


def test_the_corpus_is_fifty_tickets_with_unique_ids():
    cases = _committed()
    assert len(cases) == builder.TOTAL
    assert len({c["id"] for c in cases}) == builder.TOTAL


def test_input_carries_only_the_ticket_and_never_the_answer():
    for case in _committed():
        assert set(case["input"]) == {"ticket_id", "subject", "body", "customer_tier"}
        assert case["input"]["ticket_id"] == case["id"]
        assert case["input"]["customer_tier"] in ("free", "pro", "enterprise")


def test_every_hard_case_type_is_present_in_both_splits_or_at_least_in_train():
    cases = _committed()
    for tag in builder.HARD_TAGS:
        members = [c for c in cases if tag in c["tags"]]
        assert len(members) >= 3, tag
        assert any(c["split"] == "train" for c in members), tag
        assert any(c["split"] == "holdout" for c in members), tag


def test_the_split_is_stratified_around_seventy_percent():
    cases = _committed()
    groups: dict[str, list[dict]] = {}
    for case in cases:
        groups.setdefault(builder.stratum(case), []).append(case)
    for name, members in groups.items():
        train = sum(1 for c in members if c["split"] == "train")
        assert abs(train / len(members) - builder.TRAIN_FRACTION) <= 0.2, name


def test_priority_and_needs_human_stay_consistent_with_the_policy():
    """p0/p1 always needs a human; anger on its own never reaches p0."""
    for case in _committed():
        expected = case["expected"]
        if expected["priority"] in ("p0", "p1"):
            assert expected["needs_human"] is True, case["id"]
        if "angry-low-priority" in case["tags"]:
            assert expected["priority"] in ("p2", "p3"), case["id"]
            assert expected["needs_human"] is True, case["id"]


def test_language_does_not_correlate_with_the_answer():
    """Mixed-language tickets span severities, so language is not a shortcut."""
    priorities = {c["expected"]["priority"] for c in _committed() if "mixed-language" in c["tags"]}
    assert len(priorities) >= 3
