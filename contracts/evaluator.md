# Evaluator contract

PLAN.md §4.3. **Frozen after Phase 0.**

```
evaluators/<evaluator_id>/
  README.md      # the domain, what "good" means, the tools the agent is allowed
  cases.jsonl    # {id, split, input, expected, tags}
  score.py       # def score(expected: dict, actual: dict) -> {"passed", "score", "notes"}
```

## `cases.jsonl`

One JSON object per line:

```json
{"id": "issue_412",
 "split": "train",
 "input": {"number": 412, "title": "...", "body": "..."},
 "expected": {"labels": ["bug", "platform:windows"], "component": "pty", "priority": "p1"},
 "tags": ["windows", "duplicate-bait"]}
```

- `id` is unique within the evaluator and stable across runs — the ledger, the
  issue tracker and the compare page all key on it.
- `split` is `train` or `holdout`. Split 70/30, **stratified by tag**.
  `github_triage` uses a **temporal** split instead: train = oldest 70%,
  holdout = newest 30% (§0.1).
- `input` is passed to the agent. `expected` is passed only to `score.py`.
- `tags` describe the **hard-case type** (e.g. `sarcasm`, `deadline-not-end-date`),
  so failure analysis can group by tag. Untagged cases use `[]`.

## `score.py`

```python
def score(expected: dict, actual: dict) -> dict:
    """Return {"passed": bool, "score": float, "notes": str}."""
```

- `score` is in `[0, 1]`. `passed` is the binary verdict the gate uses.
- `notes` is a short human-readable reason; it feeds `failure_signature`, so
  keep it **normalized** (no case ids, no timestamps, no raw model output) or
  identical failures will not dedupe.
- Must be **deterministic and fully offline** — no network, no clock, no
  randomness. Eval runs read cached tool data (`fixtures/github_cache/`), never
  the live API, unless `--live` is passed.
- `actual` may be malformed or empty (the agent failed or drifted). `score.py`
  must not raise: return `{"passed": False, "score": 0.0, "notes": "..."}`.

## `README.md`

States the domain, what "good" means, and which tools the agent is allowed to
use. The architect (W3) reads this plus 5 sample train cases when generating v0.

## Holdout rule (non-negotiable)

> The improver may read train failures and their transcripts.
> **Holdout is never shown to the improver.** It is run only for reporting,
> after a fix has already been accepted on train.

Any code path that hands holdout cases, holdout transcripts or holdout scores to
the improver, the failure analyst or the reflection prompt is a bug.

## Repeats

Every case is run `EVAL_REPEATS` times (default 3). Per PLAN.md §4.1: a case's
pass rate is `passes / repeats`; a case is **stably passing** iff it passed in
every repeat; the gate uses stable passes.

## Validation

`scripts/validate_evaluators.py` (W4) checks: schema of every case, split
balance, tag coverage, and that an "always-empty" agent scores ~0 (a domain
where an empty answer scores well is not measuring anything).
