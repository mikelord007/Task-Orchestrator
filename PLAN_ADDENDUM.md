# PLAN_ADDENDUM.md — overrides PLAN.md where they conflict

## Why

A Maximor judge posted the questions Track 1 judges will actually ask:
1. How does the agent get better over time?
2. Can you show the agent's **outputs** getting better over time through its **own self-reflection and memory growing**?
3. Can it learn **complex contextual logic by analyzing data from third-party tools** (tools/MCPs/APIs) and **apply that context in later runs**?
4. Does it balance **cost-effectiveness and speed**?
Also: domain doesn't matter; don't build side features; plan the 3-minute demo early; skip login/auth. They linked Anthropic's "Demystifying evals for AI agents", "Writing effective tools for agents", and the Managed Agents docs; §J and §K adopt those.

The star of the demo is now **one agent with real third-party tool access whose memory visibly grows and whose outputs visibly improve**. The loop infrastructure (eval, gate, error bars, fix cards, drift) stays; it is what makes the improvement provable. The Luma requirement for multiple domains still stands: two domains, one of them using a real third-party API.

## §0 Non-negotiable rule: observed facts, never self-reports

The runtime records what an agent *actually did* (every LLM request/response, every tool call and return value, token usage from the API usage field, per-step timestamps) at the harness level. Nothing in the ledger, the drift watchdog, the reflection step, the failure analyst, or any chart may come from asking the agent what it did. Pass/fail comes from the grader, never from the agent's claim. This is the same principle AO applies by reading Claude Code's JSONL event files instead of trusting agent summaries.

## §A Contract changes (orchestrator applies these first, one PR)

**Ledger events (add or extend):**
- `run_started` + `trials` (int)
- `case_result` + `trial` (0..trials-1), `steps`, `tool_calls`, `tool_errors`, `rules_injected[]`, `drift_event_id?`. If a `repeat` key already exists in merged code, keep it and alias `trial = repeat`.
- `run_finished` → `split, trials, pass_at_1, pass_pow_k, pass_rate_std, pass_rate_min, pass_rate_max, total_cost_usd, p50_latency_ms, p95_latency_ms, drift_count, tokens_saved_by_drift`
- new `drift_detected {case_id, trial, step, kind: loop|budget|step_limit|off_task, evidence, action: abort|nudge, tokens_at_detection}`
- `fix_proposed` → `issue_id?, from_version, to_version, lever, failing_group{signature, tag, case_ids[], count}, hypothesis, diagnosis (≤3 plain sentences), diff_path, diff_summary, files_touched[], metric_signal?`
- `fix_accepted` → `to_version, pass_at_1_before/after, pass_pow_k_before/after, group_pass_before/after, holdout_pass_at_1_after, holdout_pass_pow_k_after, cost_per_run_before/after, tool_calls_per_task_before/after`
- `fix_rejected` → `to_version, reason: regression|no_gain|error, regressed_case_ids[], candidate_pass_at_1`
- new `memory_written {entry_id, kind: rule|tool_note|episode, source: reflection|issue, evidence_case_ids[], version}`
- new `memory_demoted {entry_id, hits, misses, version}`
- new `task_graduated {case_id, version}`
- `lever` enum: `memory | tools | prompt | orchestration | routing | grader`

**Definitions used everywhere:** `pass@1` = mean per-trial pass rate over tasks. `pass^k` (k = trials) = fraction of tasks that passed **every** trial; those tasks are the **stable pass set**. The gate uses `pass^k`. Never report a bare "accuracy".

**Agent package:** `memory.md` is replaced by a directory `agents/<id>/v<N>/memory/` containing `rules.jsonl`, `tool_notes.jsonl`, `episodes.jsonl` (schemas in §G). Tool descriptions live in `agents/<id>/v<N>/tools/` and are versioned with the package. Add `agents/<id>/v<N>/CHANGES.diff` (unified diff from v<N-1>).

**Evaluator:** `cases.jsonl` rows gain `reference_output` (must pass the grader) and may carry tags `negative:*` and `from_issue:<id>`. Temporal split for github_triage (§F).

**API (add):**
```
GET /agents/{id}/fixes                    -> [FixCard]
GET /agents/{id}/fixes/{to_version}/diff  -> text/plain
GET /agents/{id}/compare?case_id=         -> {expected, v0:{output, rules_injected[], tool_calls, tokens}, current:{...}}
GET /insights/{id} adds: pass_at_1_by_version[], pass_pow_k_by_version[] (each {version, split, mean, std, min, max}),
    memory{rules, tool_notes, mean_confidence, demotions}_by_version[], tool_stats_by_version[] (calls, errors, redundant, tool_tokens, latency per task),
    drift{count_by_kind, tokens_saved, cases_recovered_by_nudge}, graduated_count, saturated: bool
FixCard = {to_version, from_version, lever, status: accepted|rejected, failing_group, hypothesis, diagnosis, metric_signal?,
           diff_summary, files_touched[], diff_url, before{...}, after{...}, regressed_case_ids[]}
```

**Env knobs:** `EVAL_TRIALS` (default 3), `EVAL_CONCURRENCY` (4), `DRIFT_MAX_STEPS` (12), `DRIFT_TOKEN_BUDGET` (20000), `DRIFT_REPEAT_CALL_LIMIT` (3), `GITHUB_TOKEN`.

## §B Trials and error bars (W1, W2, W6, W9)

- `run_eval` runs every task `EVAL_TRIALS` times; one `case_result` per (task, trial); transcripts at `runs/<run_id>/<case_id>.t<trial>.json`.
- W1 metrics: `pass_at_1`, `pass_pow_k`, `stable_pass_set`, std/min/max over trial-level pass rates.
- Gate (W6): run the full train set on the candidate at `EVAL_TRIALS`. Accept iff (a) every task in the prior version's stable pass set is still in the candidate's stable pass set, and (b) candidate `pass@1` ≥ prior `pass@1`. Then run holdout once at `EVAL_TRIALS` and record it. A flaky task (passes 2/3) is not in the stable set and cannot cause a false regression.
- W9: pass-rate chart shows `pass@1` and `pass^k` as two lines each with a mean±std band and min/max whiskers; subtitle states `trials = N`. Train and holdout both.
- Cut floor: trials may drop to 2, never 1.

## §C Drift watchdog (W2) — `backend/runtime/drift.py`

Evaluated after every loop step from observed transcript state only:
- `loop`: same tool with same normalized args `DRIFT_REPEAT_CALL_LIMIT` times → **nudge** once (inject system message: "You have called `<tool>` with identical arguments N times. Change approach or answer with what you have."); second trigger → **abort**.
- `budget`: cumulative case tokens > `DRIFT_TOKEN_BUDGET` → abort.
- `step_limit`: steps > `DRIFT_MAX_STEPS` → abort.
- `off_task` (optional, cut first): last two assistant messages contain no required output key and no tool call → nudge with the output schema; abort on repeat.
Every trigger emits `drift_detected`. Aborted cases score as failures with `failure_signature = "drift:<kind>"` so the improver can target them. A nudged case that then passes counts toward `cases_recovered_by_nudge`. `tokens_saved` = Σ (`DRIFT_TOKEN_BUDGET − tokens_at_detection`) over aborts. Tests: fake LLM that repeats a tool call forever → assert nudge, then abort, then payloads.

## §D Fix cards (W6, W1, W5/W9, W7)

A fix card is the join of one `fix_proposed` with its `fix_accepted`/`fix_rejected` plus the diff file. W6 must fill the full payload: failing group (tag + count + case ids), a ≤3-sentence hypothesis a judge can read aloud, the actual diff at `CHANGES.diff`, before→after numbers with ±. For `memory` fixes the diff is the list of entries added; for `tools` fixes it is the description/schema diff plus before/after tool-call and tool-error counts. UI: a **Fixes** tab on the agent page (timeline, newest first, expandable diff), the same component embedded in Insights and in each issue's timeline (cards whose `failing_group.case_ids` intersect the issue's linked cases).

## §E Memory becomes the primary lever (W1, W2, W6)

`agents/<id>/v<N>/memory/`:
```
rules.jsonl       {id, rule, scope_keywords[], evidence_case_ids[], confidence, hits, misses, created_version, source: reflection|issue, demoted: bool}
tool_notes.jsonl  {id, tool, note, evidence, created_version}      e.g. "github_search_similar_issues: pass state=all when hunting duplicates"
episodes.jsonl    {version, run_id, one_line_reflection}
```
- Runtime (W2): before each case inject all `tool_notes` + top-K `rules` by keyword overlap with the input (K=12, no embeddings); write `rules_injected[]` into `case_result`. After grading, the **runtime** credits `hits`/`misses` on injected rules from the grader result. A rule with `misses > hits` after ≥4 uses is demoted (kept on disk, no longer injected) → `memory_demoted`.
- Reflection (W6, the agent's own, **first** step of `improve`): after each train run, for each failure group, run the agent's reflection prompt over (its harness-recorded transcript, the cached tool data it saw, the grader verdict + expected output) → proposed rules / tool notes with evidence case ids. Proposals go through the gate like any change (lever = `memory`). The reflection prompt must contain: "Do not evaluate your own performance; the grade is given. Explain the discrepancy using only the transcript and tool data provided." The agent is never asked whether it succeeded.
- Lever order in `improve`: `memory → tools → prompt → orchestration`.

## §F Domain A becomes `github_triage` (W3 toolbox, W4 evaluator). Domain B stays `ticket_triage` unchanged.

Drop `hackathon_extract` (no third-party tool, nothing contextual to learn). If W4 already finished it, keep it as Domain B instead of `ticket_triage` and note that in BUILD_LOG.

**Tools** (`backend/toolbox/github.py`), per Anthropic's tools post — consolidated, namespaced, NOT one wrapper per endpoint:
- `github_get_issue_context(issue_number, response_format=concise|detailed)` → title, body, author, comments, linked PRs/commits and the files they touched, in one call.
- `github_search_similar_issues(query, state=all, limit=10)` → candidate duplicates: title, labels, state, two-line summary each.
- `github_get_label_taxonomy()` → every label with description, usage count, and two example issue titles. Most contextual logic lives here.
- `github_find_component_owners(paths_or_keywords[])` → components/labels/maintainers associated with those paths or terms, from recent commits and past assignments.
Rules: unambiguous param names (`issue_number` not `id`); natural-language names over opaque ids; `concise` default, `detailed` exposes ids only for follow-ups; truncation messages say how to narrow; error messages show a valid call; descriptions written like a brief to a new hire (what it returns, when to use it, what it does NOT do).

**Cache-through:** every tool response is written to `fixtures/github_cache/<sha256(tool,args)>.json`; eval reads the cache (deterministic, offline, free); `--live` bypasses. First run populates it. Needs `GITHUB_TOKEN`.

**Task:** given an open issue → `{labels[], component, assignee?, duplicate_of?, priority}`. Ground truth = what maintainers actually applied on now-closed issues. Repo: `Untrivial-ai/agent-orchestrator` (fallback: any repo with ≥200 closed labeled issues). 60 tasks. **Temporal split**: train = oldest 70%, holdout = newest 30% (this is literally "apply context in later runs"; say so in README and demo). Grader: `passed` iff labels set-F1 ≥ 0.8 AND component exact; `score` = 0.5·labelF1 + 0.3·component + 0.2·priority. Include negatives tagged `negative:*` (issues that should get no extra label, no valid duplicate). Every task has a `reference_output` that passes the grader; `scripts/validate_evaluators.py` asserts it. Target: naive v0 at 40–60%.

## §G Show outputs getting better (W1 endpoint, W9 page + charts)

- `GET /agents/{id}/compare?case_id=` and page `/agents/[id]/compare`: side-by-side v0 vs current output for any task, with the memory entries injected in each version and tool-call counts. Pick three tasks for the demo where v0 was wrong, vN is right, and the rule that fixed it is obvious.
- Insights adds: **memory growth** (rules + tool notes count and mean confidence per version, demotions marked) and **tool-usage efficiency** (tool calls, tool errors, redundant calls, tool-response tokens, latency per task — expected to fall). With the pass-rate band, these answer judge questions 2, 3, 4.

## §J Eval rigor in the judges' vocabulary (Anthropic evals post)

- Terms in code/UI/README: **task** (case), **trial** (repeat), **grader** (score.py), **transcript**, **outcome**, **eval harness** (run_eval), **agent harness** (the loop), **eval suite** (one evaluator dir).
- Report `pass@1` and `pass^k` by name; gate on `pass^k`; README explains why consistency matters.
- **Capability suite** = train set (should start low). **Regression suite** = stable-pass tasks + all issue-derived tasks (should sit at ~100%). A task that becomes stably passing **graduates** → `task_graduated`; Insights shows a graduated counter.
- Grade **outcomes, not paths**: the grader reads final output only; tool calls/errors/tokens/latency/drift are tracked metrics, never graders. Partial credit (`score`) stays.
- **Trial isolation**: each trial starts from a clean transcript; trials never see other trials' outputs or the improver's diagnoses.
- **"Grader disagreed?"** button on any failed trial → opens an issue tagged `grader-bug`; a grader fix is a fix with lever `grader`, excluded from the agent's improvement curve.
- A task at 0% after 3 versions is flagged for review (their rule: 0% is usually a broken task, not an incapable agent).
- **Saturation**: if train `pass@1` ≥ 95% for two consecutive versions, Insights shows "capability suite saturated — add harder tasks".

## §K The `tools` lever per Anthropic's tools post (W6, W1)

The `tools` lever is not only "add a tool". In priority order it may: (1) rewrite a tool's description or parameter names, (2) change a default (`limit`, `response_format`, truncation), (3) improve a truncation/error message so the agent self-corrects, (4) consolidate two tools, (5) add a tool. Each tools diagnosis must cite the tracked-metric signal in `metric_signal` using the post's heuristics: **many redundant calls → rightsize pagination/limits; many invalid-parameter errors → clearer description or example**. W1 adds `tool_call_stats(agent_id, version)` = calls, errors, redundant calls (same tool, identical normalized args, same trial), tool-response tokens, latency — per task. README (W12): one sentence mapping our agent package to the Managed Agents shape: an agent is model + system prompt + tools + MCP servers + skills; our `memory/` plays the skills role.

## §L Worker reconciliation (orchestrator)

For each workstream: if merged → spawn a follow-up `W<n>b` on `ws/w<n>b-addendum` with the additions below; if in progress → message the session with its additions; if not started → spawn with PLAN.md block + this addendum.
- **W1** ledger: §A metrics, `pass_at_1`/`pass_pow_k`/`stable_pass_set`, `drift_stats`, `tool_call_stats`, `fix_cards()`, graduation, saturation, `/fixes`, `/compare`.
- **W2** runtime: trials, harness-level observation (§0), drift watchdog (§C, loop+budget first), memory injection + hits/misses (§E), trial isolation (§J).
- **W3** architect/toolbox: the four `github_*` tools (§F) with cache-through; architect reads `memory/` schemas.
- **W4** evaluators: `github_triage` per §F; keep `ticket_triage`; negatives; `reference_output`; validator asserts references pass.
- **W5** frontend shell: Fixes tab, Compare page, per-trial pass strip + drift badge on the results table; drop screenshot upload (text-only issues).
- **W6** improver: reflection first (§E) obeying §0; lever order; tools lever per §K; gate on `pass^k` (§B); full fix-card payloads + `CHANGES.diff` (§D).
- **W7** issues: text-only; fix timeline from fix cards; "grader disagreed?" path (§J).
- **W8** playbook: unchanged; ablation on Domain B as planned.
- **W9** insights: §B chart, memory growth + tool efficiency (§G), fix cards, drift panel, graduated counter, saturation banner.
- **W10**: keep only the per-step model field in `agent.yaml` and one measured routing change; no pseudo-lever.
- **W11/W12**: every pass rate as `pass@1` and `pass^k` with ±; one full fix card verbatim in the README; Managed-Agents sentence; demo per §N.

## §M Time check and cut order

Deadline: Sunday 6:00 PM EDT. Compute remaining hours now and write them to BUILD_LOG.md.
- If **< ~10 hours remain**: do §B, §D, §E, §G, §J on whatever domain already runs; do §F only if one worker can build the four `github_*` tools + cache in ≤ 2 hours in parallel.
- Cut order if behind: W10 → `off_task` drift kind → pass-rate-vs-cost scatter → domain comparison side-by-side (keep ablation numbers as text) → drift `nudge` (keep detect+abort) → `generate_critic` mode → Domain B improve iterations (keep the ablation) → trials to 2.
- **Never cut:** trials ≥ 2, the gate, fix-card payloads, the compare page, `BUILD_LOG.md`.

## §N Demo order (W12 writes DEMO.md to this; ~3:05)

1. (20s) The agent, its `github_*` tools, empty memory. Run v0 on one issue: wrong labels, 9 tool calls.
2. (30s) Reflection writes 3 rules + 1 tool note from tool data; show entries and evidence case ids.
3. (25s) Gate accepts; band moves up; fix card shows the memory entries added.
4. (25s) Compare page: same issue v0 vs v3 — correct labels, 4 tool calls, the rules that fired.
5. (25s) Insights: pass@1/pass^k band, memory growth, tool efficiency (cost/speed).
6. (20s) A rejected fix and a demoted rule: memory that self-corrects.
7. (20s) Holdout = newest issues never seen during improvement: "applies context in later runs." Domain B: playbook-on vs off, its own band.
8. (10s) AO board + BUILD_LOG.md + repo.
