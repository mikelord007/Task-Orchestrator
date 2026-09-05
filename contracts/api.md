# REST API contract

PLAN.md §4.5 as amended by PLAN_ADDENDUM.md section A (which wins wherever
they conflict). The frontend builds against this with mocks
(`NEXT_PUBLIC_USE_MOCKS`). **Frozen after Phase 0.**

Base URL: `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`.
No auth (skip login/auth). All timestamps ISO8601 UTC. Vocabulary: a **task**
is one `case_id`; a **trial** is one repeated attempt at a task; the
**grader** is `score.py`. Field names below are the contract; prose says task/
trial/grader.

## Endpoints

```
POST /agents                      {goal, domain, tools[], evaluator_id, use_playbook}  -> {agent_id, version: 0}
GET  /agents · GET /agents/{id} · GET /agents/{id}/versions/{n}
POST /agents/{id}/run             {split}                                              -> {run_id}
GET  /agents/{id}/runs            -> [RunSummary]
POST /agents/{id}/improve         {max_attempts, issue_id?}                            -> {job_id}
GET  /jobs/{job_id}
GET  /issues?agent_id= · POST /issues {agent_id, title, body, tags?[]} · GET /issues/{id}
POST /issues/{id}/fix
GET  /agents/{id}/fixes           -> [FixCard]  (see below)
GET  /agents/{id}/fixes/{to_version}/diff   -> text/plain unified diff
GET  /agents/{id}/compare?case_id=   -> Compare  (see below)
GET  /insights/{agent_id}         -> Insights  (see below)
GET  /insights/compare            -> per-domain series + reports/ablation.json if present
GET  /events?agent_id=&kind=&since=
GET  /playbook
GET  /evaluators
```

`POST /issues` is a plain JSON body, not multipart — issues are **text-only**
(no screenshot upload, dropped per the judge guidance). `tags[]` is optional;
its one defined use so far is the "grader disagreed?" path (below), which
sends `tags: ["grader-bug"]`.

## `GET /agents/{id}/runs`

One row per completed (or in-flight) evaluation run of this agent, newest first.

```
RunSummary = {
  run_id, agent_id, version, split: "train"|"holdout", trials,
  started_ts, finished_ts?,
  pass_at_1, pass_pow_k, total_cost_usd, p50_latency_ms, p95_latency_ms, drift_count,
  tasks: TaskResult[]
}
TaskResult = {
  case_id, passed_by_trial: bool[],       // length == trials
  score, cost_usd, latency_ms, tool_calls, tool_errors, rules_injected: string[],
  transcript_path, trace_url?, drift_kind?
}
```

`passed_by_trial` is the one genuinely per-trial field. Every other `TaskResult`
field (`score`, `cost_usd`, `latency_ms`, `tool_calls`, `tool_errors`,
`rules_injected`, `transcript_path`, `trace_url`, `drift_kind`) is taken from
**trial 0** of that task in this run — enough to show one representative
transcript per row without inflating the payload with `trials` copies; the
per-trial pass/fail strip is the part that must show every trial.

## `GET /agents/{id}/compare?case_id=`

```
Compare = {expected,
           v0:      CompareSide,
           current: CompareSide}
CompareSide = {output, rules_injected: string[], tool_calls, tokens} | null
```

Shows the **same task** at v0 and at the current version: the output, the
memory entries injected in each version, and the tool-call count. This is what
makes "the outputs got better, and here is the rule that did it" visible.

`output` and `expected` are the raw JSON objects (`actual` / `expected` as the
grader sees them). `rules_injected[]` is a list of `MemoryRule.id`. `tokens` is
`tokens_in + tokens_out` for that task. Values are taken from **trial 0** of
the most recent run of that version; if the version has never been run on that
task, the side is `null`.

## `FixCard`

Not a table. It is the join of one `fix_proposed` with its matching
`fix_accepted` / `fix_rejected` on `to_version`, plus the diff file at `diff_path`.

```
FixCard = {
  to_version, from_version, lever, status: accepted|rejected,
  failing_group: {signature, tag, count, case_ids[]},
  hypothesis, diagnosis, metric_signal?,
  diff_summary, files_touched[], diff_url,
  before: {pass_at_1, pass_pow_k, group_pass, cost_per_run, tool_calls_per_task},
  after:  {pass_at_1, pass_pow_k, group_pass, holdout_pass_at_1, holdout_pass_pow_k,
           cost_per_run, tool_calls_per_task},
  regressed_case_ids[]   // only when rejected
}
```

- `status` is derived, never stored (rule §2.4/§4.1). A `fix_proposed` with no
  matching accept/reject is a fix still in flight; Phase 0 reading: omit it
  from `/agents/{id}/fixes`.
- `diff_url` is `/agents/{id}/fixes/{to_version}/diff`.
- `metric_signal` is set only for `lever = tools` fixes (the tracked-metric
  heuristic that drove the diagnosis, e.g. "12 redundant `list_issues` calls
  per task" — section K); `null` otherwise.
- For `lever = memory`, `diff_summary` describes the memory entries added or
  changed rather than a text diff; `diff_url` still serves the unified diff of
  the jsonl files.
- `before`/`after` field names mirror `fix_accepted`'s flat float fields
  exactly (see `contracts/events.py` — a fix event is one observed fact, not a
  nested stat). On a **rejected** card, `after` carries only `pass_at_1` (from
  `fix_rejected.candidate_pass_at_1`); every other `after` field is `null`.

## `Insights`

```
GET /insights/{agent_id} -> Insights

VersionPoint = {version, split: "train"|"holdout", mean, std, min, max}
Marker       = {version, ts, kind, lever?, diagnosis?}          // chart annotations

Insights = {
  pass_at_1_by_version:  VersionPoint[],
  pass_pow_k_by_version: VersionPoint[],
  cost_by_version:    {version, cost_per_run}[],
  latency_by_version: {version, p50_ms, p95_ms}[],
  fixes_by_lever: {[lever]: number},
  regressions_caught: number,
  issues: {open, closed},
  lessons_count: number,
  memory_by_version: {version, rules, tool_notes, mean_confidence, demotions}[],
  tool_stats_by_version: {version, split, calls, errors, redundant, tool_tokens, latency_ms}[],
  drift: {count_by_kind: {[kind]: number}, tokens_saved, cases_recovered_by_nudge},
  graduated_count: number,
  saturated: boolean,
  flagged_tasks: string[],       // case_ids at 0% across the last 3 versions
  markers: Marker[]
}
```

- `pass_at_1_by_version` / `pass_pow_k_by_version` replace the old single
  `pass_rate_by_version` — the pass-rate chart plots both lines, each with a
  mean±std band and min/max whiskers, subtitled `trials = N`. Train and
  holdout both appear (`split` distinguishes them).
- `memory_by_version` and `tool_stats_by_version` are the two extra charts
  that answer "does memory grow" and "does tool use get more efficient":
  memory growth (rules + tool notes count and mean confidence per version,
  demotions marked) and tool-usage efficiency. `tool_stats_by_version` values
  are per-task averages for that version and split — `calls`, `errors`, and
  `redundant` (same tool + identical normalized args within one trial) are all
  expected to fall as the agent improves.
- `graduated_count` is the running total of `task_graduated` events.
  `saturated` is `true` once train `pass_at_1` >= 0.95 for two consecutive
  versions (Insights should show "capability suite saturated — add harder
  tasks"). `flagged_tasks` lists tasks stuck at 0% for the last 3 versions —
  section J's rule that this usually means a broken task, not an incapable
  agent.
- Empty ledger returns honest empty arrays / zeros, never placeholder numbers
  (rule §2.4).

## "Grader disagreed?"

Any failed trial can be flagged from the UI: `POST /issues` with a prefilled
title/body and `tags: ["grader-bug"]`. A fix that follows from such an issue
uses `lever = grader` and is **excluded from the agent's improvement curve**
(it fixes the measuring stick, not the agent).

## Conventions

- Errors: standard FastAPI `{"detail": "..."}` with 4xx/5xx.
- `POST /agents/{id}/run` and `POST /agents/{id}/improve` are **async**: they
  return immediately with `{run_id}` / `{job_id}`; progress is polled from
  `GET /jobs/{job_id}`.

## Internal Python signature

Workers code against this directly (not over HTTP):

```python
improver.improve(agent_id: str, max_attempts: int = 3, issue_id: str | None = None) -> ImproveResult
```

`ImproveResult` carries the attempts made and the outcome of each
(`accepted` / `rejected` + reason), the final `current_version`, and the ids of
the `fix_proposed` / `fix_accepted` / `fix_rejected` events emitted. W6 owns its
concrete definition; the call signature above is what other workers may rely on.
