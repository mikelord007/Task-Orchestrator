"""Tests for `scripts/validate_evaluators.py`.

The first test is the one that matters day to day: the evaluators actually
committed to this repo must validate. The rest prove the validator has teeth, by
building deliberately broken evaluators in a tmp dir and asserting it rejects
them.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "validate_evaluators", REPO_ROOT / "scripts" / "validate_evaluators.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


validator = _load_module()

GOOD_SCORE_PY = """
def score(expected, actual):
    if not isinstance(actual, dict):
        return {"passed": False, "score": 0.0, "notes": "no_output"}
    ok = expected.get("answer") == actual.get("answer")
    return {"passed": ok, "score": 1.0 if ok else 0.0, "notes": "ok" if ok else "mismatch"}
"""


def _write_evaluator(
    root: Path,
    name: str = "toy",
    *,
    cases: list[dict] | None = None,
    score_py: str = GOOD_SCORE_PY,
    files: tuple[str, ...] = ("README.md", "cases.jsonl", "score.py"),
) -> Path:
    """A minimal valid evaluator, unless the caller breaks one of the pieces."""
    if cases is None:
        cases = [
            {
                "id": f"c-{i}",
                "split": "train" if i < 7 else "holdout",
                "input": {"q": f"question {i}"},
                "expected": {"answer": f"a{i}"},
                "tags": ["easy"],
            }
            for i in range(10)
        ]
    path = root / name
    path.mkdir(parents=True)
    if "README.md" in files:
        (path / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    if "cases.jsonl" in files:
        (path / "cases.jsonl").write_text(
            "".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8"
        )
    if "score.py" in files:
        (path / "score.py").write_text(score_py, encoding="utf-8")
    return path


def _errors(root: Path) -> list[str]:
    return validator.validate(root).errors


# ------------------------------------------------------------------ the real thing


def test_the_committed_evaluators_validate():
    report = validator.validate(REPO_ROOT / "evaluators")
    assert report.errors == []


def test_main_exits_zero_on_the_committed_evaluators(capsys):
    assert validator.main(["--quiet"]) == 0
    assert "OK" in capsys.readouterr().out


def test_main_exits_non_zero_on_a_broken_evaluator(tmp_path, capsys):
    _write_evaluator(tmp_path, files=("cases.jsonl", "score.py"))
    assert validator.main(["--evaluators-dir", str(tmp_path), "--quiet"]) == 1
    assert "missing README.md" in capsys.readouterr().out


def test_discover_skips_directories_without_cases(tmp_path):
    _write_evaluator(tmp_path, "toy")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "notes").mkdir()
    assert [p.name for p in validator.discover(tmp_path)] == ["toy"]


# ------------------------------------------------------------------- schema checks


def test_a_valid_evaluator_produces_no_errors(tmp_path):
    _write_evaluator(tmp_path)
    assert _errors(tmp_path) == []


def test_no_evaluators_at_all_is_an_error(tmp_path):
    assert any("no evaluator directories" in e for e in _errors(tmp_path))


def test_duplicate_ids_are_rejected(tmp_path):
    cases = [
        {
            "id": "same",
            "split": "train" if i < 7 else "holdout",
            "input": {},
            "expected": {"answer": "a"},
            "tags": [],
        }
        for i in range(10)
    ]
    _write_evaluator(tmp_path, cases=cases)
    assert any("duplicate id" in e for e in _errors(tmp_path))


@pytest.mark.parametrize("bad_split", ["test", "", None, 3])
def test_an_unknown_split_is_rejected(tmp_path, bad_split):
    cases = [
        {
            "id": f"c-{i}",
            "split": bad_split if i == 0 else ("train" if i < 7 else "holdout"),
            "input": {},
            "expected": {"answer": "a"},
            "tags": [],
        }
        for i in range(10)
    ]
    _write_evaluator(tmp_path, cases=cases)
    assert any("split must be one of" in e for e in _errors(tmp_path))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input", "not a dict", "`input` must be an object"),
        ("expected", ["nope"], "`expected` must be an object"),
        ("tags", "easy", "`tags` must be a list of strings"),
        ("tags", [1, 2], "`tags` must be a list of strings"),
        ("id", "", "missing a non-empty string `id`"),
    ],
)
def test_malformed_case_fields_are_rejected(tmp_path, field, value, message):
    cases = [
        {
            "id": f"c-{i}",
            "split": "train" if i < 7 else "holdout",
            "input": {},
            "expected": {"answer": "a"},
            "tags": ["easy"],
        }
        for i in range(10)
    ]
    cases[0][field] = value
    _write_evaluator(tmp_path, cases=cases)
    assert any(message in e for e in _errors(tmp_path))


def test_unparseable_lines_are_reported(tmp_path):
    path = _write_evaluator(tmp_path)
    with (path / "cases.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json}\n")
    assert any("not valid JSON" in e for e in _errors(tmp_path))


def test_an_empty_cases_file_is_an_error(tmp_path):
    _write_evaluator(tmp_path, cases=[])
    assert any("cases.jsonl is empty" in e for e in _errors(tmp_path))


# -------------------------------------------------------------------- split checks


def test_an_empty_holdout_split_is_rejected(tmp_path):
    cases = [
        {"id": f"c-{i}", "split": "train", "input": {}, "expected": {"answer": "a"}, "tags": []}
        for i in range(10)
    ]
    _write_evaluator(tmp_path, cases=cases)
    errors = _errors(tmp_path)
    assert any("split 'holdout' is empty" in e for e in errors)
    assert any("train share" in e for e in errors)


def test_a_tag_missing_from_train_is_rejected(tmp_path):
    cases = [
        {
            "id": f"c-{i}",
            "split": "train" if i < 7 else "holdout",
            "input": {},
            "expected": {"answer": "a"},
            "tags": ["easy"] if i < 8 else ["hard"],
        }
        for i in range(10)
    ]
    _write_evaluator(tmp_path, cases=cases)
    assert any("'hard' never appears in train" in e for e in _errors(tmp_path))


def test_a_single_case_tag_only_in_holdout_is_tolerated(tmp_path):
    cases = [
        {
            "id": f"c-{i}",
            "split": "train" if i < 7 else "holdout",
            "input": {},
            "expected": {"answer": "a"},
            "tags": ["easy"] if i < 9 else ["rare"],
        }
        for i in range(10)
    ]
    _write_evaluator(tmp_path, cases=cases)
    assert _errors(tmp_path) == []


# ------------------------------------------------------------------- scorer checks


def test_a_scorer_with_the_wrong_signature_is_rejected(tmp_path):
    _write_evaluator(tmp_path, score_py="def score(expected):\n    return {}\n")
    assert any("exactly two positional arguments" in e for e in _errors(tmp_path))


def test_a_scorer_that_does_not_import_is_rejected(tmp_path):
    _write_evaluator(tmp_path, score_py="def score(expected, actual)\n")
    assert any("not importable" in e for e in _errors(tmp_path))


def test_a_scorer_without_a_score_function_is_rejected(tmp_path):
    _write_evaluator(tmp_path, score_py="def grade(expected, actual):\n    return {}\n")
    assert any("not importable" in e for e in _errors(tmp_path))


@pytest.mark.parametrize(
    ("returned", "message"),
    [
        ('"passed"', "expected a dict"),
        ('{"passed": 1, "score": 1.0, "notes": ""}', "`passed` must be a bool"),
        ('{"passed": True, "score": "1", "notes": ""}', "`score` must be a number"),
        ('{"passed": True, "score": 4.0, "notes": ""}', "within [0, 1]"),
        ('{"passed": True, "score": 1.0, "notes": None}', "`notes` must be a string"),
    ],
)
def test_a_malformed_score_result_is_rejected(tmp_path, returned, message):
    _write_evaluator(tmp_path, score_py=f"def score(expected, actual):\n    return {returned}\n")
    assert any(message in e for e in _errors(tmp_path))


def test_a_scorer_that_fails_its_own_ground_truth_is_rejected(tmp_path):
    _write_evaluator(
        tmp_path,
        score_py=(
            "def score(expected, actual):\n"
            '    return {"passed": False, "score": 0.0, "notes": "never"}\n'
        ),
    )
    assert any("do not pass against their own `expected`" in e for e in _errors(tmp_path))


def test_an_always_empty_agent_that_passes_is_rejected(tmp_path):
    _write_evaluator(
        tmp_path,
        score_py=(
            "def score(expected, actual):\n"
            '    return {"passed": True, "score": 1.0, "notes": "ok"}\n'
        ),
    )
    errors = _errors(tmp_path)
    assert any("always-empty agent passes" in e for e in errors)
    assert any("always-empty agent means" in e for e in errors)


def test_an_always_empty_agent_scoring_above_the_ceiling_is_rejected(tmp_path):
    _write_evaluator(
        tmp_path,
        score_py=(
            "def score(expected, actual):\n"
            '    ok = expected.get("answer") == actual.get("answer")\n'
            '    return {"passed": ok, "score": 1.0 if ok else 0.5, "notes": "ok"}\n'
        ),
    )
    assert any("always-empty agent means" in e for e in _errors(tmp_path))
