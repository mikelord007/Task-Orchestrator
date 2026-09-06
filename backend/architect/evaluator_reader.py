"""Read an evaluator's README and a sample of its train cases (step 1, no LLM call)."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ROOT = "evaluators"
SAMPLE_SIZE = 5


class EvaluatorNotFoundError(Exception):
    pass


def read_evaluator(evaluator_id: str, root: str | Path = DEFAULT_ROOT) -> dict:
    """``{'evaluator_id', 'readme', 'sample_cases', 'expected_keys'}``.

    ``sample_cases`` is up to the first 5 ``split == "train"`` rows in
    ``cases.jsonl``, in file order. ``expected_keys`` is the union of keys
    across those samples' ``expected`` dicts, in first-seen order -- this is
    what the drafted prompt tells the agent to answer with.
    """
    base = Path(root) / evaluator_id
    readme_path = base / "README.md"
    cases_path = base / "cases.jsonl"
    if not readme_path.is_file() or not cases_path.is_file():
        raise EvaluatorNotFoundError(
            f"evaluator {evaluator_id!r} not found under {base} "
            "(expected README.md and cases.jsonl)"
        )

    readme = readme_path.read_text(encoding="utf-8")

    train_cases: list[dict] = []
    with cases_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case.get("split") == "train":
                train_cases.append(case)
            if len(train_cases) >= SAMPLE_SIZE:
                break

    expected_keys: list[str] = []
    for case in train_cases:
        for key in case.get("expected") or {}:
            if key not in expected_keys:
                expected_keys.append(key)

    return {
        "evaluator_id": evaluator_id,
        "readme": readme,
        "sample_cases": train_cases,
        "expected_keys": expected_keys,
    }
