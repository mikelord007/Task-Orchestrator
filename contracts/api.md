# REST API contract

PLAN.md §4.5 plus the §0.3 compare endpoint. The frontend builds against this
with mocks (`NEXT_PUBLIC_USE_MOCKS`). **Frozen after Phase 0.**

Base URL: `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`.
No auth (§0: skip login/auth). All timestamps ISO8601 UTC.

## Endpoints (§4.5, verbatim)

```
POST /agents                      {goal, domain, tools[], evaluator_id, use_playbook}  -> {agent_id, version: 0}
GET  /agents · GET /agents/{id} · GET /agents/{id}/versions/{n}
POST /agents/{id}/run             {split}                                              -> {run_id}
POST /agents/{id}/improve         {max_attempts, issue_id?}                            -> {job_id}
GET  /jobs/{job_id}
GET  /issues?agent_id= · POST /issues (multipart: agent_id, title, body, screenshot?) · GET /issues/{id}
POST /issues/{id}/fix
GET  /agents/{id}/fixes           -> [FixCard]  (see below)
GET  /agents/{id}/fixes/{to_version}/diff   -> text/plain unified diff
GET  /insights/{agent_id}         -> {pass_rate_by_version[{version, split, mean, std, min, max}],
                                      cost_by_version[], latency_by_version[],
                                      fixes_by_lever{}, regressions_caught, issues{open,closed}, lessons_count,
                                      drift{count_by_kind{}, tokens_saved, cases_recovered_by_nudge},
                                      markers[]}
GET  /insights/compare            -> per-domain series + reports/ablation.json if present
GET  /events?agent_id=&kind=&since=
GET  /playbook
GET  /evaluators
```

## Added by §0.3

```
GET  /agents/{id}/compare?case_id=   -> {expected,
                                         v0:      {output, rules_injected[], tool_calls, tokens},
                                         current: {output, rules_injected[], tool_calls, tokens}}
```

Shows the **same case** at v0 and at the current version: the output, the memory
entries injected in each version, and the tool-call count. This is what makes
"the outputs got better, and here is the rule that did it" visible.

`output` and `expected` are the raw JSON objects (`actual` / `expected` as
`score.py` sees them). `rules_injected[]` is a list of `MemoryRule.id`.
`tokens` is `tokens_in + tokens_out` for that case. Values are taken from the
`case_result` of **repeat 0** of the most recent run of that version; if the
version has never been run on that case, the side is `null`.

## `FixCard` (§4.5)

Not a table. It is the join of one `fix_proposed` with its matching
`fix_accepted` / `fix_rejected` on `to_version`, plus the diff file at `diff_path`.

```
FixCard = {
  to_version, from_version, lever, status: accepted|rejected,
  failing_group: {signature, tag, count, case_ids[]},
  hypothesis, diagnosis,
  diff_summary, files_touched[], diff_url,
  before: {train_mean, train_std, group_pass, cost_per_run},
  after:  {train_mean, train_std, group_pass, holdout_mean, holdout_std, cost_per_run},
  regressed_case_ids[]   // only when rejected
}
```

- `status` is derived, never stored (rule §4.1). A `fix_proposed` with no
  matching accept/reject is a fix still in flight; W1 decides whether to surface
  it (Phase 0 reading: omit it from `/agents/{id}/fixes`).
- `diff_url` is `/agents/{id}/fixes/{to_version}/diff`.
- For `lever = memory`, `diff_summary` describes the memory entries added or
  changed rather than a text diff (§0.2); `diff_url` still serves the unified
  diff of the jsonl files.
- On a rejected card, `after` carries only `train_mean` / `train_std` (from
  `fix_rejected.train_pass_rate_candidate`); the other fields are `null`.

## Shared shapes

```
PassRateStat  = {mean, std, min?, max?}
VersionPoint  = {version, split: "train"|"holdout", mean, std, min, max}
Marker        = {version, ts, kind, lever?, diagnosis?}          // chart annotations
Insights      = {pass_rate_by_version: VersionPoint[],
                 cost_by_version: {version, cost_per_run}[],
                 latency_by_version: {version, p50_ms, p95_ms}[],
                 fixes_by_lever: {[lever]: number},
                 regressions_caught: number,
                 issues: {open, closed},
                 lessons_count: number,
                 drift: {count_by_kind: {[kind]: number}, tokens_saved, cases_recovered_by_nudge},
                 markers: Marker[],
                 memory_growth_by_version: {version, rules, tool_notes, mean_confidence, demotions}[],   // §0.3
                 tool_efficiency_by_version: {version, tool_calls_per_case, tool_errors_per_case,
                                   tokens_per_case, latency_ms_per_case}[]}                   // §0.3
Job           = {job_id, agent_id, kind, status: queued|running|done|error,
                 attempts, max_attempts, current_step?, result?, error?, created_ts, updated_ts}
Issue         = {id, agent_id, title, body, source: human|auto, status: open|closed,
                 failure_signature?, linked_case_ids[], fixed_version?, created_ts}
```

`memory_growth_by_version` and `tool_efficiency_by_version` are the two charts §0.3 adds to Insights;
they are part of the `GET /insights/{agent_id}` response, not new endpoints.

## Conventions

- Errors: standard FastAPI `{"detail": "..."}` with 4xx/5xx.
- `POST /agents/{id}/run` and `POST /agents/{id}/improve` are **async**: they
  return immediately with `{run_id}` / `{job_id}`; progress is polled from
  `GET /jobs/{job_id}`.
- `POST /issues` is `multipart/form-data` for shape compatibility, but the
  `screenshot` field is **dropped in §0.4** — text only. The field stays in the
  contract as optional and ignored so the frontend form does not need a contract
  change if it is ever restored.
- Empty ledger returns honest empty arrays / zeros, never placeholder numbers
  (rule §2.4).

## Internal Python signature

Workers code against this directly (not over HTTP):

```python
improver.improve(agent_id: str, max_attempts: int = 3, issue_id: str | None = None) -> ImproveResult
```

`ImproveResult` carries the attempts made and the outcome of each
(`accepted` / `rejected` + reason), the final `current_version`, and the ids of
the `fix_proposed` / `fix_accepted` / `fix_rejected` events emitted. W6 owns its
concrete definition; the call signature above is what other workers may rely on.
