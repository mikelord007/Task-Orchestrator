from __future__ import annotations

import pytest

from backend.architect.evaluator_reader import EvaluatorNotFoundError, read_evaluator


def test_reads_readme_and_up_to_five_train_cases(evaluator_dir):
    result = read_evaluator("widget_triage", root=evaluator_dir)
    assert "widget_triage" in result["readme"]
    assert [case["id"] for case in result["sample_cases"]] == [
        "c1",
        "c2",
    ]  # holdout excluded


def test_expected_keys_is_the_union_in_first_seen_order(evaluator_dir):
    result = read_evaluator("widget_triage", root=evaluator_dir)
    assert result["expected_keys"] == ["labels", "component", "priority"]


def test_caps_samples_at_five(tmp_path):
    base = tmp_path / "evaluators" / "big"
    base.mkdir(parents=True)
    (base / "README.md").write_text("x", encoding="utf-8")
    rows = [
        f'{{"id": "c{i}", "split": "train", "input": {{}}, "expected": {{"a": 1}}, "tags": []}}'
        for i in range(10)
    ]
    (base / "cases.jsonl").write_text("\n".join(rows), encoding="utf-8")
    result = read_evaluator("big", root=tmp_path / "evaluators")
    assert len(result["sample_cases"]) == 5


def test_missing_evaluator_raises_a_clear_error(tmp_path):
    with pytest.raises(EvaluatorNotFoundError):
        read_evaluator("does_not_exist", root=tmp_path / "evaluators")
