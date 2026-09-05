"""Validate every evaluator in `evaluators/` against the contract in PLAN.md 4.3.

    python scripts/validate_evaluators.py [--evaluators-dir DIR] [--quiet]

Exits non-zero if anything is wrong. Checks, per evaluator directory:

1. **Layout** - `README.md`, `cases.jsonl` and `score.py` all exist.
2. **Case schema** - every line is a JSON object with a non-empty string `id`
   (unique within the evaluator), `split` in {`train`, `holdout`}, a dict `input`,
   a dict `expected`, and a list of string `tags`.
3. **Split balance** - both splits are non-empty, the train share is inside
   `SPLIT_TOLERANCE` of 70%, and every tag that appears at all appears in `train`.
   Counts per split and per tag are reported either way.
4. **Scorer** - `score.py` imports, exposes `score`, takes exactly two positional
   arguments, and returns `{passed: bool, score: float in [0,1], notes: str}`.
5. **Ground truth is reachable** - scoring each case's `expected` against itself
   passes with score 1.0. A case no correct answer can pass is a broken case.
6. **An always-empty agent scores ~0** - feeding `{}` as `actual` to every case
   must never pass and must have a mean score below `EMPTY_MEAN_MAX`.

Stdlib only. No network.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATORS_DIR = REPO_ROOT / "evaluators"

VALID_SPLITS = ("train", "holdout")
TRAIN_TARGET = 0.7
SPLIT_TOLERANCE = 0.08
EMPTY_MEAN_MAX = 0.15
REQUIRED_FILES = ("README.md", "cases.jsonl", "score.py")


class Report:
    """Accumulates errors and human-readable lines for one validation run."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.lines: list[str] = []

    def fail(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def say(self, message: str) -> None:
        self.lines.append(message)


def discover(evaluators_dir: Path) -> list[Path]:
    """Evaluator directories, i.e. any child directory holding a `cases.jsonl`."""
    if not evaluators_dir.is_dir():
        return []
    return sorted(
        path
        for path in evaluators_dir.iterdir()
        if path.is_dir()
        and not path.name.startswith((".", "_"))
        and (path / "cases.jsonl").exists()
    )


def load_scorer(score_path: Path):
    spec = importlib.util.spec_from_file_location(
        f"_validate_{score_path.parent.name}_score", score_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {score_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score


def load_cases(cases_path: Path, name: str, report: Report) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for lineno, line in enumerate(cases_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            report.fail(f"{name} line {lineno}", f"not valid JSON ({exc.msg})")
            continue
        if not isinstance(case, dict):
            report.fail(f"{name} line {lineno}", "case is not a JSON object")
            continue

        where = f"{name} line {lineno}"
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            report.fail(where, "missing a non-empty string `id`")
        elif case_id in seen:
            report.fail(where, f"duplicate id {case_id!r}")
        else:
            seen.add(case_id)

        if case.get("split") not in VALID_SPLITS:
            report.fail(where, f"split must be one of {VALID_SPLITS}, got {case.get('split')!r}")
        if not isinstance(case.get("input"), dict):
            report.fail(where, "`input` must be an object")
        if not isinstance(case.get("expected"), dict):
            report.fail(where, "`expected` must be an object")
        tags = case.get("tags")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            report.fail(where, "`tags` must be a list of strings")

        cases.append(case)
    if not cases:
        report.fail(name, "cases.jsonl is empty")
    return cases


def check_split_balance(cases: list[dict], name: str, report: Report) -> None:
    per_split: dict[str, int] = {split: 0 for split in VALID_SPLITS}
    per_tag: dict[str, dict[str, int]] = {}
    for case in cases:
        split = case.get("split")
        if split in per_split:
            per_split[split] += 1
        tags = case.get("tags")
        if not isinstance(tags, list):
            continue  # already reported by the schema pass
        for tag in tags:
            if not isinstance(tag, str):
                continue
            counts = per_tag.setdefault(tag, {s: 0 for s in VALID_SPLITS})
            if split in counts:
                counts[split] += 1

    total = sum(per_split.values())
    report.say(f"  cases: {total}  train={per_split['train']}  holdout={per_split['holdout']}")
    if total:
        share = per_split["train"] / total
        report.say(f"  train share: {share:.2f} (target {TRAIN_TARGET:.2f})")
        if abs(share - TRAIN_TARGET) > SPLIT_TOLERANCE:
            report.fail(
                name,
                f"train share {share:.2f} is outside {TRAIN_TARGET:.2f} +/- {SPLIT_TOLERANCE:.2f}",
            )
    for split in VALID_SPLITS:
        if not per_split[split]:
            report.fail(name, f"split {split!r} is empty")

    report.say("  tags:")
    for tag in sorted(per_tag):
        counts = per_tag[tag]
        tag_total = counts["train"] + counts["holdout"]
        # A tag with a single case cannot land in both splits, so it is reported
        # but not an error; anything rarer than that is a corpus problem, not a
        # split problem.
        note = "  (single-case tag)" if tag_total == 1 else ""
        report.say(
            f"    {tag:<28} train={counts['train']:<4} holdout={counts['holdout']:<4}"
            f" total={tag_total}{note}"
        )
        if not counts["train"] and tag_total > 1:
            report.fail(name, f"tag {tag!r} never appears in train, so it can never be improved")


def check_scorer_signature(scorer, name: str, report: Report) -> bool:
    if not callable(scorer):
        report.fail(name, "score.py exposes `score` but it is not callable")
        return False
    params = [
        p
        for p in inspect.signature(scorer).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) != 2:
        report.fail(
            name,
            f"score() must take exactly two positional arguments (expected, actual),"
            f" got {[p.name for p in params]}",
        )
        return False
    return True


def check_result_shape(result: object, where: str, report: Report) -> bool:
    if not isinstance(result, dict):
        report.fail(where, f"score() returned {type(result).__name__}, expected a dict")
        return False
    ok = True
    if not isinstance(result.get("passed"), bool):
        report.fail(where, "score() result `passed` must be a bool")
        ok = False
    value = result.get("score")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        report.fail(where, "score() result `score` must be a number")
        ok = False
    elif not 0.0 <= float(value) <= 1.0:
        report.fail(where, f"score() result `score` must be within [0, 1], got {value}")
        ok = False
    if not isinstance(result.get("notes"), str):
        report.fail(where, "score() result `notes` must be a string")
        ok = False
    return ok


def check_scoring(scorer, cases: list[dict], name: str, report: Report) -> None:
    empty_scores: list[float] = []
    empty_passes: list[str] = []
    self_failures: list[str] = []

    for case in cases:
        expected = case.get("expected")
        if not isinstance(expected, dict):
            continue
        case_id = case.get("id", "?")

        self_result = scorer(expected, dict(expected))
        if not check_result_shape(self_result, f"{name} case {case_id}", report):
            return
        if not self_result["passed"] or float(self_result["score"]) < 1.0:
            self_failures.append(case_id)

        empty_result = scorer(expected, {})
        if not check_result_shape(empty_result, f"{name} case {case_id} (empty actual)", report):
            return
        empty_scores.append(float(empty_result["score"]))
        if empty_result["passed"]:
            empty_passes.append(case_id)

    if self_failures:
        report.fail(
            name,
            f"{len(self_failures)} case(s) do not pass against their own `expected`:"
            f" {self_failures[:5]}",
        )

    if empty_scores:
        mean = sum(empty_scores) / len(empty_scores)
        report.say(f"  empty-agent mean score: {mean:.3f} (max {EMPTY_MEAN_MAX})")
        if mean >= EMPTY_MEAN_MAX:
            report.fail(
                name, f"an always-empty agent means {mean:.3f}, expected < {EMPTY_MEAN_MAX}"
            )
    if empty_passes:
        report.fail(
            name, f"an always-empty agent passes {len(empty_passes)} case(s): {empty_passes[:5]}"
        )


def validate_evaluator(path: Path, report: Report) -> None:
    name = path.name
    report.say(f"\n{name}")

    for filename in REQUIRED_FILES:
        if not (path / filename).exists():
            report.fail(name, f"missing {filename}")
    if not (path / "cases.jsonl").exists():
        return

    cases = load_cases(path / "cases.jsonl", name, report)
    if not cases:
        return
    check_split_balance(cases, name, report)

    score_path = path / "score.py"
    if not score_path.exists():
        return
    try:
        scorer = load_scorer(score_path)
    except (ImportError, AttributeError, SyntaxError) as exc:
        report.fail(name, f"score.py is not importable with a `score` function: {exc}")
        return
    if check_scorer_signature(scorer, name, report):
        check_scoring(scorer, cases, name, report)


def validate(evaluators_dir: Path) -> Report:
    report = Report()
    evaluators = discover(evaluators_dir)
    if not evaluators:
        report.fail(str(evaluators_dir), "no evaluator directories found")
        return report
    report.say(f"Validating {len(evaluators)} evaluator(s) in {evaluators_dir}")
    for path in evaluators:
        validate_evaluator(path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the evaluators.")
    parser.add_argument("--evaluators-dir", type=Path, default=DEFAULT_EVALUATORS_DIR)
    parser.add_argument("--quiet", action="store_true", help="Only print failures.")
    args = parser.parse_args(argv)

    report = validate(args.evaluators_dir)
    if not args.quiet:
        for line in report.lines:
            print(line)
    if report.errors:
        print(f"\nFAILED: {len(report.errors)} problem(s)")
        for error in report.errors:
            print(f"  - {error}")
        return 1
    print("\nOK: all evaluators valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
