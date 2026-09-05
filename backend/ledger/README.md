# `backend/ledger` — the append-only ledger and every metric derived from it

The `events` table (PLAN.md §4.1) is the only record of what happened. Nothing
stores a derived status: **every number in the product is recomputed from events
on read**, so a chart can never disagree with the facts behind it.

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
- **Observed facts, never self-reports** (PLAN.md §2.8). `passed` comes from
  `score.py`; `rules_injected` is written by the runtime; rule hits and misses
  are computed here from those two. Nothing asks the agent how it did.
- **No fabricated numbers.** Empty input returns `None`/`{}`/`[]`, never a `0`
  standing in for missing data. `test_empty.py` pins that for every function.

## Definitions

For a run with `repeats = R`:

- a **case's pass rate** is `passes / R`;
- **`mean`** is the mean over cases of that per-case rate;
- **`std` / `min` / `max`** are the population std / min / max over the `R`
  *run-level* rates — one per repeat index, `passes-in-that-repeat / cases`;
- a case is **stably passing** iff it passed in every repeat. The gate protects
  exactly this set, which is why a flaky case can never be reported as a
  regression.

Every metric reads the **latest finished run** of a `(agent, version, split)`;
a run with no `run_finished` event is ignored.

## `query.py`

| function | returns |
|---|---|
| `events(conn, kind=, agent_id=, agent_version=, run_id=, since=, limit=)` | matching `Event`s, oldest first, payload decoded. `kind` takes one kind or many; `since` is an inclusive ISO8601 lower bound on `ts`. |
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
| `pass_rate(conn, agent_id, version, split)` | `{mean, std, min, max, repeats, case_count}` for the latest finished run — all `None` when there is none. |
| `stable_pass_set(conn, agent_id, version)` | `set[case_id]` of train cases that passed in *every* repeat. |
| `cost_per_run(conn, agent_id, version, split)` | total USD for the whole run (every case at every repeat), or `None`. |
| `latency_percentiles(conn, agent_id, version, split)` | `{p50, p95}` in ms over case executions, linear interpolation. |
| `fixes_by_lever(conn, agent_id)` | `{lever: count}` of **accepted** fixes. Rejected attempts show up as fix cards and in `regressions_caught`. |
| `regressions_caught(conn, agent_id)` | count of `fix_rejected` with `reason = "regression"`. |
| `issue_stats(conn, agent_id)` | `{open, closed}` — `issue_opened` events joined to `issues.status`; an id with no row counts as open. |
| `lessons_count(conn)` | distinct lessons in `lesson_recorded`, across all agents. |
| `drift_stats(conn, agent_id)` | `{count_by_kind, tokens_saved, cases_recovered_by_nudge, count_by_version}`. `tokens_saved` sums `DRIFT_TOKEN_BUDGET − tokens_at_detection` over aborts. |
| `series_by_version(conn, agent_id)` | `{pass_rate_by_version[], cost_by_version[], latency_by_version[]}`, one row per `(version, split)` that has a finished run. |
| `markers(conn, agent_id)` | chart annotations: `issue_opened`, `fix_accepted`, `fix_rejected` (with lever, hypothesis, diagnosis), `memory_demoted`, and `drift_cluster` (drift grouped per version). |
| `rule_stats(conn, agent_id)` | `{entry_id: {hits, misses, uses}}` from `case_result.rules_injected` × `passed`. |
| `memory_growth_by_version(conn, agent_id, root=)` | `[{version, rules, rules_written, tool_notes, mean_confidence, demotions}]`. `rules` is written-minus-demoted (active); `mean_confidence` comes from `agents/<id>/v<N>/memory/rules.jsonl`, `None` when that snapshot is absent. |
| `tool_efficiency_by_version(conn, agent_id)` | `[{version, split, tool_calls_per_case, tool_errors_per_case, tokens_per_case, latency_ms_per_case}]`, per case *execution*. |
| `fix_cards(conn, agent_id)` | `FixCard`s per `contracts/api.md`, newest first. |
| `fix_diff(conn, agent_id, to_version, root=)` | the unified diff text at `fix_proposed.diff_path`, or `None`. |
| `compare(conn, agent_id, case_id, root=)` | `{expected, v0, current}` — outputs read from the harness transcripts. |
| `insights(conn, agent_id, root=)` | the whole `GET /insights/{id}` payload. |
| `insights_compare(conn, root=)` | `{by_domain, ablation}` for `GET /insights/compare`. |

### Fix cards

A card is the join of one `fix_proposed` with its `fix_accepted` / `fix_rejected`
by `to_version`, plus the diff file on disk — there is no fixes table.

- `status` is `accepted`, `rejected`, or `proposed` for a fix whose gate has not
  reported yet. Consumers should treat `proposed` as in-flight.
- Accepted cards take `before`/`after` straight from the `fix_accepted` payload.
  `fix_rejected` only records the candidate's train rate, so a rejected card's
  `before` is recomputed from the ledger at `from_version`.
- `lever = memory` cards carry `memory_entries` — the `memory_written` payloads
  for that version — so the UI can show the entries instead of a text diff.
- `diff_url` is always `/agents/{id}/fixes/{to_version}/diff`.

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
`repeats = 3`, stable and flaky cases, drift aborts and a nudge recovery, an
accepted memory fix and a rejected prompt fix with diffs on disk, memory
entries, injected rules, issues and lessons — into a sqlite connection plus a
filesystem root. It is deliberately small enough that every expected number in
`test_metrics.py` is written out by hand. W9 can reuse it to render against real
shapes instead of ad-hoc mocks:

```python
from backend.tests.ledger.seed import build
seeded = build(sqlite3.connect(":memory:"), tmp_path)
```
