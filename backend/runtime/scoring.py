"""Evaluator loading and scoring.

``passed`` comes from the evaluator's ``score.py`` and from nowhere else
(PLAN.md rule 2.8). The runtime imports it by path and calls
``score(expected, actual) -> {passed, score, notes}``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_EVALUATORS_DIR = Path("evaluators")

ScoreFn = Callable[[dict[str, Any], Any], dict[str, Any]]


class EvaluatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScoreResult:
    passed: bool
    score: float
    notes: str


def evaluator_dir(evaluator_id: str, evaluators_dir: Path | str = DEFAULT_EVALUATORS_DIR) -> Path:
    return Path(evaluators_dir) / evaluator_id


def load_cases(directory: Path | str, split: str | None = None) -> list[dict[str, Any]]:
    """Read ``cases.jsonl``, optionally filtered to one split."""
    path = Path(directory) / "cases.jsonl"
    if not path.exists():
        raise EvaluatorError(f"evaluator has no cases.jsonl: {path}")
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        if split and case.get("split") != split:
            continue
        cases.append(case)
    return cases


def load_scorer(directory: Path | str) -> ScoreFn:
    """Import the evaluator's ``score.py`` by path and return its ``score``."""
    path = Path(directory) / "score.py"
    if not path.exists():
        raise EvaluatorError(f"evaluator has no score.py: {path}")
    module_name = f"_evaluator_score_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise EvaluatorError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        # The module object (and the "score" callable's closure over it)
        # stays alive via our own references; sys.modules only needed the
        # entry during exec_module for relative imports inside score.py.
        sys.modules.pop(module_name, None)
    scorer = getattr(module, "score", None)
    if not callable(scorer):
        raise EvaluatorError(f"{path} does not define score(expected, actual)")
    return scorer


def score_case(scorer: ScoreFn, expected: dict[str, Any], actual: Any) -> ScoreResult:
    """Call the evaluator. A scorer that raises is a failure, never a crash."""
    try:
        raw = scorer(expected, actual)
    except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
        return ScoreResult(
            passed=False, score=0.0, notes=f"scorer error: {type(exc).__name__}: {exc}"
        )
    if not isinstance(raw, dict):
        return ScoreResult(
            passed=False,
            score=0.0,
            notes=f"scorer returned {type(raw).__name__}, expected dict",
        )
    return ScoreResult(
        passed=bool(raw.get("passed")),
        score=float(raw.get("score") or 0.0),
        notes=str(raw.get("notes") or ""),
    )
