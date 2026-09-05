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
 "reference_output": {"labels": ["bug", "platform:windows"], "component": "pty", "priority": "p1"},
 "tags": ["windows", "duplicate-bait"]}
```

- `id` is unique within the evaluator and stable across runs — the ledger, the
  issue tracker and the compare page all key on it. In prose and UI this is a
  **task** (section J); the field name stays `case_id`/`id`.
- `split` is `train` or `holdout`. Split 70/30, **stratified by tag**.
  `github_triage` uses a **temporal** split instead: train = oldest 70%,
  holdout = newest 30% (this is literally "apply context in later runs" —
  say so in the README and the demo).
- `input` is passed to the agent. `expected` is passed only to `score.py`.
- `reference_output` is an answer shaped exactly like the agent's output JSON
  that **must pass the grader**: `score(expected, reference_output).passed`
  is `True`. It is not shown to the agent; it exists so
  `scripts/validate_evaluators.py` can prove every task is answerable and the
  grader is not itself broken (section J: "a task at 0% after 3 versions is
  usually a broken task, not an incapable agent" — a task whose own
  `reference_output` fails the grader is broken by definition and must be
  fixed before it ships).
- `tags` describe the **hard-case type** (e.g. `sarcasm`, `deadline-not-end-date`),
  so failure analysis can group by tag. Untagged cases use `[]`. Two tag
  prefixes are reserved:
  - `negative:*` — a task where the correct answer is "nothing extra" (e.g.
    `negative:no_extra_labels`, `negative:not_duplicate`). Without negatives, an
    agent that over-labels everything can look good on set-F1.
  - `from_issue:<id>` — a regression task created from a human-filed issue
    (`issues.id`); links the case back to the report that produced it.

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

## Trials

Every task is run `EVAL_TRIALS` times (default 3; `EVAL_REPEATS` is a
deprecated alias, see `.env.example`). A task's pass rate is `passes /
trials`. Two numbers are reported, never a bare "accuracy":

- **pass@1** — the mean per-trial pass rate over tasks.
- **pass^k** (k = trials) — the fraction of tasks that passed **every**
  trial. Those tasks are the **stable pass set**; the gate uses `pass^k`.

The **capability suite** is the train set (expected to start low). The
**regression suite** is the stable-pass tasks plus every `from_issue:*` task
(expected to sit near 100% — a drop there is a regression, full stop).

## Validation

`scripts/validate_evaluators.py` (W4) checks: schema of every case (including
`reference_output`), that `score(expected, reference_output).passed` is `True`
for every task, split balance, tag coverage, and that an "always-empty" agent
scores ~0 (a domain where an empty answer scores well is not measuring
anything).
