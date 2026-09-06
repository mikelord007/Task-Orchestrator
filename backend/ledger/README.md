# `backend/ledger` — the append-only ledger and every metric derived from it

The `events` table (PLAN_ADDENDUM.md §A) is the only record of what happened.
Nothing stores a derived status: **every number in the product is recomputed
from events on read**, so a chart can never disagree with the facts behind it.

Terminology (PLAN_ADDENDUM.md §J): a **task** is one evaluator case, a **trial**
is one repeated execution of a task (`case_result.trial`; `repeat` is accepted
as a read-time alias for events written before the addendum renamed it), and
the **grader** is `score.py`.

| module | role |
|---|---|
| `emit.py` | the only writer. Validates against `contracts/events.py`, appends. Never updates, never deletes. |
| `query.py` | read layer: rows in, `Event` objects with decoded payloads out. |
| `metrics.py` | pure functions over those events (plus files on disk for diffs, transcripts and memory snapshots). |
| `api.py` | the FastAPI router. Thin: each handler calls one metric. |

## Rules this module is built to keep

- **Append-only.** `metrics.py` and `query.py` never write. `test_purity.py`
  proves it by row count, by `total_changes`, and by running the whole insights
  payload against a read-only sqlite connection.
- **Observed facts, never self-reports** (PLAN_ADDENDUM.md §0). `passed` comes
  from the grader; `rules_injected` is written by the runtime; rule hits and
  misses are computed here from those two. Nothing asks the agent how it did.
- **No fabricated numbers.** Empty input returns `None`/`{}`/`[]`, never a `0`
  standing in for missing data. `test_empty.py` pins that for every function.

## Definitions

For a run with `trials = T`:

- **pass@1** is the mean per-trial pass rate over tasks: total passes over
  `tasks * T`. Equivalently the mean over tasks of `passes / T`.
- **pass^k** (k = trials) is the fraction of tasks that passed *every* trial.
  Those tasks are the **stable pass set**; the gate accepts/rejects on pass^k.
- `pass_at_1()` and `pass_pow_k()` report the same `std` / `min` / `max`,
  computed over the per-trial pass-rate array (one rate per trial index:
  tasks-passed-in-that-trial / task-count) — they differ only in what `mean`
  measures.
- A task is **stably passing** iff it passed in every trial. The gate protects
  exactly this set, which is why a flaky task can never be reported as a
  regression.

Every metric reads the **latest finished run** of a `(agent, version, split)`;
a run with no `run_finished` event is ignored.

## `query.py`

| function | returns |
|---|---|
| `events(conn, kind=, agent_id=, agent_version=, run_id=, since=, limit=)` | matching `Event`s, oldest first, payload decoded. `kind` takes one kind or many. `since` accepts either an event id cursor -- an `int`, or a digit string as arrives over HTTP (`id > since`, exclusive) -- or an ISO8601 UTC timestamp (`ts >= since`, inclusive), matching `backend.ledger.emit.read()`. |
| `Event.trial()` | the event's trial index, reading `trial` and falling back to the pre-addendum `repeat` field. |
| `runs(conn, agent_id, version=, split=, finished_only=True)` | `Run` objects pairing `run_started` with `run_finished`. |
| `latest_run(conn, agent_id, version, split)` | the most recent finished `Run`, or `None`. |
| `case_results(conn, run_id)` | every `case_result` of one run. |
| `agent_row(conn, agent_id)` / `agent_rows(conn)` | `agents` rows as dicts; `None`/`[]` when absent. |
| `issue_status(conn, issue_ids)` | `issue id -> status`; unknown ids map to `None` so the caller decides. |

## `metrics.py`

Every function takes the sqlite connection first. The few that read the
filesystem take an optional `root` (defaults to `$TASK_ORCHESTRATOR_ROOT`, else
the repo root).

| function | returns |
|---|---|
| `pass_at_1(conn, agent_id, version, split)` | `{mean, std, min, max, trials, task_count}` — mean per-trial pass rate over tasks. All `None` when there is no finished run. |
| `pass_pow_k(conn, agent_id, version, split)` | same shape; `mean` is the stable-pass fraction. Shares `std`/`min`/`max` with `pass_at_1` (same per-trial rate array). |
| `stable_pass_set(conn, agent_id, version)` | `set[case_id]` of train tasks that passed in **every declared trial** of the latest train run — a task missing a trial (e.g. 1 of 3 recorded) is never stable even if every recorded trial passed. |
| `cost_per_run(conn, agent_id, version, split)` | total USD for the whole run (every task at every trial), or `None`. |
| `latency_percentiles(conn, agent_id, version, split)` | `{p50, p95}` in ms over task executions, linear interpolation. |
| `fixes_by_lever(conn, agent_id)` | `{lever: count}` of **accepted** fixes (`memory\|tools\|prompt\|orchestration\|routing\|grader`). Rejected attempts show up as fix cards and in `regressions_caught`. |
| `regressions_caught(conn, agent_id)` | count of `fix_rejected` with `reason = "regression"`. |
| `issue_stats(conn, agent_id)` | `{open, closed}` — `issue_opened` events joined to `issues.status`; an id with no row counts as open. |
| `lessons_count(conn)` | distinct lessons in `lesson_recorded`, across all agents. |
| `drift_stats(conn, agent_id)` | `{count_by_kind, tokens_saved, cases_recovered_by_nudge, count_by_version}`. `tokens_saved` sums `DRIFT_TOKEN_BUDGET − tokens_at_detection` over aborts. `cases_recovered_by_nudge` joins on `case_result.drift_event_id` first, falling back to a (run, task, trial) tuple match only for older events without that field. |
| `series_by_version(conn, agent_id)` | `{pass_at_1_by_version[], pass_pow_k_by_version[], cost_by_version[], latency_by_version[]}`, one row per `(version, split)` that has a finished run. |
| `markers(conn, agent_id)` | chart annotations: `issue_opened`, `fix_accepted`, `fix_rejected` (with lever, hypothesis, diagnosis, `metric_signal`), `memory_demoted`, and `drift_cluster` (drift grouped per version). |
| `graduated_count(conn, agent_id)` | the running total of `task_graduated` events for this agent (a plain count, per `contracts/api.md` — a task that regresses and later re-graduates counts twice). |
| `saturated(conn, agent_id)` | `bool` — train pass@1 ≥ 0.95 for the last two consecutive finished train runs. |
| `zero_pass_tasks(conn, agent_id)` | `[case_id]` stuck at 0% across the last 3 consecutive finished train runs; `[]` until that much history exists. Exposed in insights as `flagged_tasks`. |
| `rule_stats(conn, agent_id)` | `{entry_id: {hits, misses, uses}}` from `case_result.rules_injected` × `passed`. |
| `memory_by_version(conn, agent_id, root=)` | `[{version, rules, rules_written, tool_notes, mean_confidence, demotions}]`. `rules` is written-minus-demoted (active); `mean_confidence` comes from `agents/<id>/v<N>/memory/rules.jsonl`, `None` when that snapshot is absent. |
| `tool_call_stats(conn, agent_id, version, split, root=)` | `{tasks: {case_id: {...}}, aggregate: {...}}` — `calls, errors, redundant, tool_tokens, latency_ms, tool_tokens_estimated`, derived from the transcript's `steps[]` (see below), else a coarser fallback from `case_result` (in which case `redundant`/`tool_tokens`/`tool_tokens_estimated` are honestly `None`, not `0`/`False`). |
| `tool_stats_by_version(conn, agent_id, root=)` | `[{version, split, calls, errors, redundant, tool_tokens, latency_ms, tool_tokens_estimated}]`, the aggregate from `tool_call_stats` per `(version, split)`, sharing one transcript-read cache across all of them. |
| `fix_cards(conn, agent_id, root=)` | `FixCard`s per `contracts/api.md`, newest first. |
| `fix_diff(conn, agent_id, to_version, root=)` | the unified diff text at `fix_proposed.diff_path`, or `None`. Refuses a `diff_path` that resolves outside the repo root. |
| `compare(conn, agent_id, case_id, root=)` | `{expected, v0, current}` — outputs read from the harness transcripts. |
| `insights(conn, agent_id, root=)` | the whole `GET /insights/{id}` payload. |
| `insights_compare(conn, root=)` | `{by_domain, ablation}` for `GET /insights/compare`. |

### Tool call stats — reading the transcript

`tool_call_stats` needs per-call detail that `case_result` alone doesn't carry
(redundant calls, tool-response tokens). It derives that from the transcript's
`steps[]` (`contracts/transcript.py`): each `tool_call` step (`tool`, `args`) is
paired with the `tool_return` step immediately after it (`error`, `tokens_in`).
A "redundant" call is the same tool with identical normalized args repeated
within one trial; the grouping key prefers a `tool_call` step's own
`normalized_args` (sorted keys, stripped/lowercased strings -- W2's harness
extension beyond `contracts/transcript.py`, read via `getattr` since
`TranscriptStep` allows extra fields) so redundancy detection agrees with the
drift watchdog's loop check, falling back to our own `json.dumps(args,
sort_keys=True)` when a step doesn't carry it. `tool_tokens_estimated` mirrors
another such extension, `tool_return.tokens_estimated`: `True` if any call in
scope had its tokens estimated rather than measured, `False` if none did,
`None` if there is no transcript detail at all. Reading a transcript goes
through `load_transcript` (so a malformed file is caught, not crashed on) and
is memoized per absolute path within one `tool_call_stats`/`tool_stats_by_version`
call — transcripts are immutable once written, so re-reading one is pure waste.
When a transcript is missing or fails to parse, the fallback reads the coarser
`case_result` fields (`tool_calls`, `tool_errors`) and reports
`redundant`/`tool_tokens`/`tool_tokens_estimated` as `None` rather than guessing.

### Fix cards

A card is the join of one `fix_proposed` with its `fix_accepted` / `fix_rejected`
by `to_version`, plus the diff file on disk — there is no fixes table.

- `status` is `accepted` or `rejected` **only**. A `fix_proposed` with no
  matching accept/reject yet is a fix still in flight and is omitted from the
  list entirely (`contracts/api.md`: "Phase 0 reading: omit it from
  `/agents/{id}/fixes`") — never a third `status: "proposed"` value.
- If two proposals ever target the same `to_version`, the newest one wins (by
  event id), so a card never mixes one proposal's diff/hypothesis with
  another's outcome.
- Accepted cards take `before`/`after` straight from the `fix_accepted` payload
  (`pass_at_1`, `pass_pow_k`, `group_pass`, `cost_per_run`, `tool_calls_per_task`,
  plus `holdout_pass_at_1`/`holdout_pass_pow_k` in `after`).
  `fix_rejected` only records the candidate's `pass@1`, so a rejected card's
  `before` is recomputed from the ledger at `from_version`.
- `lever = memory` cards carry `memory_entries` — one entry per `memory_written`
  event for that version, merged with its on-disk detail from
  `agents/<id>/v<N>/memory/{rules,tool_notes}.jsonl` (rule text, confidence,
  tool note, evidence — fields `MemoryWritten` itself forbids) — so the UI can
  show the entries instead of a text diff.
- `metric_signal` (optional on `fix_proposed`) appears on the card **only**
  when `lever == "tools"` (`contracts/api.md`: "set only for lever=tools
  fixes ... null otherwise"), even if the raw event carries one for another
  lever. `markers()` is not so restricted -- it is an undocumented chart
  annotation, not `FixCard`, and still surfaces whatever `metric_signal` the
  proposal has.
- `diff_url` is always `/agents/{id}/fixes/{to_version}/diff`.

### Documented deltas beyond `contracts/api.md`

A few fields go beyond the frozen contract; none replace a contract field,
they only add detail alongside it.

- `cost_by_version` rows add `split` and `cost_per_task` next to the
  contract's `{version, cost_per_run}`.
- `drift_stats`'s `count_by_version` (int-keyed) is not in the `drift` shape
  in `contracts/api.md`.
- `insights()` adds `agent_id`, `domain`, `current_version`, `trials`, and
  `rule_stats` alongside the documented fields.
- `pass_at_1`/`pass_pow_k` (the functions) return `trials`/`task_count`
  alongside `{mean, std, min, max}`.

## Endpoints (`api.py`)

```
GET /events?agent_id=&kind=&run_id=&since=&limit=
GET /insights/compare                       # registered before the next line
GET /insights/{agent_id}
GET /agents/{id}/fixes                      # -> [FixCard]
GET /agents/{id}/fixes/{to_version}/diff    # -> text/plain, 404 if no diff
GET /agents/{id}/compare?case_id=           # -> {expected, v0, current}
```

`/insights/compare` **must** stay registered before `/insights/{agent_id}`, or
`compare` is parsed as an agent id.

Mount with:

```python
from backend.ledger.api import router as ledger_router

app.include_router(ledger_router)
```

## Test fixture

`backend/tests/ledger/seed.py` builds a complete scenario — two versions at
`trials = 3`, stable and flaky tasks, drift aborts and a nudge recovery, an
accepted memory fix (with a `metric_signal`) and a rejected prompt fix with
diffs on disk, memory entries (including a demoted rule), injected rules,
`task_graduated` events for only the tasks newly stable each version, and
issues and lessons — into a sqlite connection plus a filesystem root. Every
event goes through the real `backend.ledger.emit.emit`, and every transcript
is written via `contracts.transcript.Transcript(...).write()`, so the fixture
is contract-valid, not an invented shape. It is deliberately small enough that
every expected number in `test_metrics.py` is written out by hand. W9 can
reuse it to render against real shapes instead of ad-hoc mocks:

```python
from backend.tests.ledger.seed import build

seeded = build(sqlite3.connect(":memory:"), tmp_path)
```

`saturated()`'s true-case and `zero_pass_tasks()`'s flagged-task case need more
finished-run history than this scenario carries (2 versions); those are tested
against small standalone ledgers built inline in `test_metrics.py` instead of
extending the shared fixture.
