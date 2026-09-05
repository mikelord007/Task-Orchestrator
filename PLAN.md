# Task Orchestrator — Build Plan for the AO Orchestrator

> **You are the AO orchestrator for this repo. Read this entire file before spawning anything.**
> This is a 30-hour hackathon build (Syndicate by Maximor, Track 1: Automated Agent Engineering).
> Every block marked **[WORKER]** must be a **separate AO worker session** on its own branch with its own PR.
> Do not implement worker tasks yourself. Your job is: Phase 0, dependency ordering, spawning workers in
> parallel, PR review, CI-failure routing, merging, and keeping `BUILD_LOG.md` current.

---

## 0. Addendum — Sept 6 judge clarification (READ FIRST; where this conflicts with a later section, this wins)

A Maximor judge posted the questions Track 1 judges will actually ask:

1. How does the agent get better over time?
2. Can you show the agent's **outputs** getting better over time through its **own self-reflection and memory growing**?
3. Can it learn **complex contextual logic by analyzing data from third-party tools** (tools / MCPs / APIs) and **apply that context in later runs**?
4. Does it balance **cost-effectiveness and speed**?

Plus: the domain doesn't matter; don't overbuild; plan the 3-minute demo early; skip login/auth.

**What this changes:** the star of the demo is now **one agent with real third-party tool access whose memory visibly grows and whose outputs visibly improve**. The loop infrastructure in §4–§8 (eval, gate, error bars, fix cards, drift) stays — it is what makes the improvement *provable* — but it is the supporting cast. The one real gap in the original plan against this rubric is that **neither domain used a third-party tool**; that is what 0.1 fixes. The multi-domain requirement from the Luma spec still stands and is unaffected. Five concrete changes follow. Ownership: 0.1 → W3 + W4 · 0.2 → W1 + W2 + W6 · 0.3 → W1 + W9 · 0.4 → orchestrator · 0.6 → W12.

**These two judges are not in conflict.** AO's founder wants a *system* that improves agents from *observed* facts (never self-reports); the Maximor judge wants to *see* one agent's memory grow and its outputs improve via *reflection*. Reflection here means the agent reasons over its **harness-recorded** transcript and the **`score.py`-graded** outcome to *propose* memory; the gate then tests the proposal empirically. Observed facts in, hypotheses out, validated before use. Rule §2.8 is unchanged and is what makes reflection trustworthy.

### 0.1 Domain swap — Domain A becomes `github_triage` (a real third-party API)

- **Tools** in `backend/toolbox/github.py`, thin wrappers over the GitHub REST API with a PAT in `GITHUB_TOKEN`: `list_issues(state, labels, since, page)`, `get_issue(number)`, `list_issue_comments(number)`, `list_labels()`, `search_issues(q)`, `get_file(path)`, `list_recent_commits(path?)`. Write tool descriptions the way Anthropic's "writing tools for agents" post recommends: what it returns, when to use it, what it does *not* do.
- **Cache-through:** every tool response is written to `fixtures/github_cache/<sha256(request)>.json`. Eval runs read the cache (deterministic, offline, free, no rate limits); a `--live` flag bypasses it. The first run populates it. This preserves §4.3's determinism rule *and* counts as third-party tool access.
- **Task:** given an open issue, produce `{labels[], component, assignee?, duplicate_of?, priority}`. Ground truth = what the maintainers actually applied on now-closed issues.
- **Repo:** `Untrivial-ai/agent-orchestrator` (rich labels, active maintainers, and it is the judge's own project — the agent learns how AO's maintainers triage AO). Fallback: any repo with ≥200 closed, labeled issues.
- **Cases:** 60 closed issues. **Temporal split**: train = oldest 70%, holdout = newest 30%. This is literally "apply that context in later runs"; say so in the README and the demo.
- **`score.py`:** `passed` iff labels set-F1 ≥ 0.8 **and** component exact; `score` = 0.5·labelF1 + 0.3·component + 0.2·priority.
- **Contextual logic the agent must learn from tool data** (and which the memory store makes visible): what each label means in this repo, file path → component mapping, maintainer conventions (e.g. Windows/ConPTY reports → a specific label), duplicate patterns, who owns what.
- **Domain B stays `ticket_triage` exactly as specified in W4.** It is the second distinct domain the Luma spec asks for and the target of the playbook ablation. Only `hackathon_extract` is dropped — it is HTML parsing with no third-party tool, so it is the weakest domain against both judges' criteria. (Alternative if W4 has already built `hackathon_extract` and time is short: keep it as Domain B instead of `ticket_triage`; the ablation works either way.)

### 0.2 Memory becomes structured, self-written, and self-correcting (replaces flat `memory.md`)

`agents/<id>/v<N>/memory/`:

```
rules.jsonl       # {id, rule, scope_keywords[], evidence_case_ids[], confidence, hits, misses, created_version, source: reflection|issue}
tool_notes.jsonl  # {id, tool, note, evidence, created_version}   e.g. "list_issues paginates at 100; pass state=all when hunting duplicates"
episodes.jsonl    # one-line reflection per run
```

- **Runtime (W2):** before each case, inject *all* `tool_notes` plus the top-K `rules` by keyword overlap with the issue text (K = 12, no embeddings). Record `rules_injected[]` in `case_result`. After scoring, credit `hits` / `misses` on the injected rules. A rule with `misses > hits` after ≥ 4 uses is **demoted** (kept on disk, no longer injected) — emit `memory_demoted`. Memory that corrects itself is a demo beat.
- **Reflection (W6, new first step — the agent's *own*):** after each train run, for each failure group, run the agent's reflection prompt over (its transcript, the tool data it saw, the expected answer) → proposed rules / tool notes, each with evidence case ids. These go through the **gate** like any other change (lever = `memory`). **Lever order is now `memory → tools → prompt → orchestration`:** memory first because it is cheapest and because it is what the judges asked to see.
- **Reflection obeys rule §2.8 (observed facts, never self-reports).** Its *inputs* are the harness-recorded transcript (every request, response, tool call, tool return, token count), the cached tool data, and the `score.py` verdict. The agent is never asked "did you succeed" or "what did you do"; it is *shown* what it did and asked why the graded outcome was wrong. Its *outputs* are proposals only: a rule is accepted into the injected set by the gate, and its `hits`/`misses` are computed by the runtime from `score.py` results on cases where the runtime injected it — never by the agent's own assessment. `rules_injected[]` is written by the runtime, not by the agent. The reflection prompt must include the line: "Do not evaluate your own performance; the grade is given. Explain the discrepancy using only the transcript and tool data provided."
- **Ledger:** add `memory_written {entry_id, kind: rule|tool_note|episode, source, evidence_case_ids[], version}` and `memory_demoted {entry_id, hits, misses, version}`. `case_result` gains `tool_calls`, `tool_errors`, `rules_injected[]`.
- Fix cards for `memory` fixes show the new/changed entries instead of a text diff.

### 0.3 Show the outputs getting better, not only the curve

- `GET /agents/{id}/compare?case_id=` → `{expected, v0: {output, rules_injected[], tool_calls, tokens}, current: {output, rules_injected[], tool_calls, tokens}}`.
- Page `/agents/[id]/compare`: side-by-side output diff for any case, with the memory entries injected in each version and the tool-call count. **Pick three cases for the demo where v0 was wrong and vN is right and the rule that fixed it is obvious.**
- Insights gets two new charts: **memory growth** (rules + tool notes count and mean confidence per version, demotions marked) and **tool-usage efficiency** (tool calls per case, tool errors per case, tokens per case, latency per case — all expected to fall). With the pass-rate band, these answer questions 2, 3, and 4 directly.

### 0.4 Scope adjustments

- **Drop:** `hackathon_extract` (replaced by `github_triage`), screenshot upload on issues (text only — the judge said not to spend time on side features, and issue text alone drives the regression-case path), `generate_critic` mode. The last two are orchestrator judgment calls and are trivially reversible if a worker has already finished them.
- **Shrink W10:** keep only the per-step model field in `agent.yaml` and one measured routing change; skip the pseudo-lever. Cost/speed is still a judged question, so the tool-efficiency chart in 0.3 carries that story.
- **Keep:** two domains, repeats / error bars, the gate, fix cards, drift (loop + budget only), playbook with the Domain B ablation.

### 0.5 Time check

If fewer than ~10 hours remain when you read this: do 0.2 and 0.3 on whatever domain already runs and swap the demo to 0.6. Do 0.1 only if one worker can build the GitHub toolbox + cache in ≤ 2 hours in parallel with everything else.

### 0.6 Demo reorder (replaces the ordering in §9; same shots, new priority)

1. **(20s)** The agent, its GitHub tools, its empty memory. Run v0 on one issue: wrong labels, 9 tool calls.
2. **(30s)** Reflection writes 3 rules + 1 tool note *from tool data*. Show the entries and their evidence case ids.
3. **(25s)** Gate accepts; the band moves up; the fix card shows the memory entries added.
4. **(25s)** Compare page: the same issue at v0 vs v3 — correct labels, 4 tool calls, the rules that fired.
5. **(25s)** Insights: pass-rate band, memory growth, tool-efficiency (cost/speed), all moving together.
6. **(20s)** A rejected fix and a demoted rule: memory that self-corrects.
7. **(20s)** Holdout = the newest issues, never seen during improvement: "applies context in later runs." Then Domain B (`ticket_triage`): playbook-on vs playbook-off v0 numbers, and its own band. "Tasks it has never seen before."
8. **(10s)** AO board + `BUILD_LOG.md` + repo link.

*(Runs ~3:05; trim shot 5 if needed.)*

---

## 1. Mission

*(Read §0 first. §0.1–0.4 modify what follows.)*

Task Orchestrator is a system that, given only **(a) a goal, (b) a set of available tools, and (c) an evaluator**, will:

1. **Generate** a specialized agent (architecture + prompt + tools + memory),
2. **Run** it against the evaluator — every case **repeated N times** so pass rates carry error bars, with a **drift watchdog** that catches agents looping or wandering mid-run,
3. **Analyze** where it fails,
4. **Improve** it along four levers — `prompt`, `tools`, `memory`, `orchestration` — and gate every change so regressions are rejected. Every accepted fix is shown as a **fix card**: failing group → hypothesis → lever → actual diff → before/after.

Every outcome is written to an append-only ledger; every chart is a query over that ledger. Humans can file GitHub-style Issues (with screenshots) that become regression cases. Lessons from improving one agent are distilled into a **playbook** so the next agent, in a *different domain*, starts better. That cross-domain transfer is the proof that the *system* improves, not just one agent.

Three things this build does that most competing submissions will not: **error bars** (reliability is a named metric), **legible fixes** (the mechanism, not just the curve), and **drift detection** (mid-run course correction).

**Judging weights to design against:** AO usage & build process 25% · technical execution & reliability 25% · track fit & measurable gains 25% · demo 15% · innovation 10%. The judges will count AO sessions in the demo video.

---

## 2. Non-negotiables (orchestrator rules)

1. **One AO worker session per [WORKER] block.** Branch name `ws/<id>-<slug>` (e.g. `ws/w2-runtime`). One PR per workstream. Every PR includes tests and must pass CI before merge.
2. **Phase 0 lands on `main` before any Phase 1 worker spawns.** Phase 1 PRs merge before Phase 2 workers spawn, except where a "Depends" line says a worker may start early.
3. **`contracts/` is frozen after Phase 0.** A worker that needs a contract change opens a GitHub issue labeled `contract-change` and stops. You decide, apply it in a small separate PR, and notify affected sessions.
4. **No fabricated numbers anywhere.** Charts read only from the ledger. Empty ledger → honest empty state. Flat or negative results are reported, never massaged.
5. **Scope discipline.** A worker more than 2h over its budget cuts features to hit its acceptance criteria. No gold-plating.
6. **`BUILD_LOG.md` is demo evidence.** Append every spawned session: session id, workstream, branch, PR link, outcome, timestamps. Seed it with your own session id.
7. Workers run `make test` and `make lint` locally before opening a PR. Workers never touch files outside their "Owns" paths without asking you.
8. **Observed facts, never self-reports.** The runtime records what an agent *actually did* (every LLM request/response, every tool call and its return value, token usage from the API, wall-clock timings) at the harness level. Nothing in the ledger, the drift detector, the failure analyst, or any chart may come from asking the agent what it did. Pass/fail comes from `score.py`, never from the agent's own claim of success. This is the same principle AO applies by reading Claude Code's JSONL event files instead of trusting agent summaries.

---

## 3. Stack (fixed — do not relitigate)

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, SQLite (`sqlite3` + thin repository layer), pydantic v2, `uv` |
| LLM access | One module `backend/llm.py` using an OpenAI-compatible client. Env: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_STRONG`, `LLM_MODEL_CHEAP`. Returns text, tool calls, and usage. Has a cost table for both models. |
| Tracing | `neatlogs` SDK, `NEATLOGS_API_KEY`. Every eval case is one trace. If the key is absent, skip Neatlogs but **always** persist the full local transcript JSON. |
| Frontend | Next.js 15 (app router), TypeScript, Tailwind, Recharts. Single `api.ts` client mirroring §4.5. |
| Repo | `backend/ · frontend/ · contracts/ · agents/ · evaluators/ · fixtures/ · playbook/ · runs/ · reports/ · scripts/ · BUILD_LOG.md · README.md · DEMO.md` |
| CI | GitHub Actions: `pytest`, `ruff`, `tsc --noEmit`, `next build` |
| Dev | `Makefile`: `dev` (both servers), `test`, `lint`, `seed`, `demo` |
| Eval knobs | `EVAL_REPEATS` (default **3**; every case runs this many times, pass rate is reported as mean ± spread), `EVAL_CONCURRENCY` (default 4), `DRIFT_MAX_STEPS` (default 12), `DRIFT_TOKEN_BUDGET` (default 20k per case), `DRIFT_REPEAT_CALL_LIMIT` (default 3) |

---

## 4. Core contracts (Phase 0 output — everything builds against these)

### 4.1 Event ledger — `contracts/events.py`

Append-only. **Never store display status; derive it.** All metrics are pure functions over this table.

```sql
events(
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,        -- ISO8601 UTC
  kind          TEXT NOT NULL,
  agent_id      TEXT,
  agent_version INTEGER,
  run_id        TEXT,
  lever         TEXT,                 -- prompt | tools | memory | orchestration | routing
  payload       TEXT NOT NULL         -- JSON
)
```

| kind | required payload keys |
|---|---|
| `agent_created` | goal, domain, tools[], evaluator_id, orchestration, applied_lessons[] |
| `run_started` | split (train\|holdout), case_count, repeats |
| `case_result` | case_id, **repeat** (0..repeats-1), passed, score, tokens_in, tokens_out, cost_usd, latency_ms, steps, trace_url?, transcript_path, failure_signature?, drift_event_id? |
| `drift_detected` | case_id, repeat, step, kind (loop\|budget\|off_task\|step_limit), evidence, action (abort\|nudge), tokens_at_detection |
| `run_finished` | split, repeats, pass_rate_mean, pass_rate_std, pass_rate_min, pass_rate_max, total_cost_usd, p50_latency_ms, p95_latency_ms, drift_count, tokens_saved_by_drift |
| `issue_opened` | issue_id, source (human\|auto), title, failure_signature? |
| `issue_linked_case` | issue_id, case_id |
| `fix_proposed` | issue_id?, from_version, to_version, lever, **failing_group** {signature, tag, case_ids[], count}, **hypothesis**, diagnosis, **diff_path** (unified diff on disk), diff_summary, files_touched[] |
| `fix_accepted` | to_version, train_pass_rate_before (mean±std), train_pass_rate_after (mean±std), **group_pass_before**, **group_pass_after**, holdout_pass_rate_after (mean±std), cost_per_run_before, cost_per_run_after |
| `fix_rejected` | to_version, reason (regression\|no_gain\|error), regressed_case_ids[], train_pass_rate_candidate |
| `lesson_recorded` | lesson_id, lever, trigger, lesson, source_agent_id, source_issue_id? |

**Pass rate definition (used everywhere):** for a run with `repeats = R`, each case's pass rate is (passes / R). The run's `pass_rate_mean` is the mean over cases; `pass_rate_std` is the std over the R per-repeat run-level pass rates. A case counts as **stably passing** iff it passed in every repeat; the gate uses stable passes.

A **fix card** is not a separate table. It is the join of one `fix_proposed` with its matching `fix_accepted` or `fix_rejected`, plus the diff file at `diff_path`.

Pydantic models for every payload live in `contracts/events.py`. `ledger.emit()` validates before insert.

### 4.2 Agent package — `contracts/agent.py` + `contracts/agent_package.md`

Immutable snapshot per version at `agents/<agent_id>/v<N>/`:

```
agent.yaml      # name, version, domain, model_strong, model_cheap, tools: [names],
                # orchestration: single | planner_worker | generate_critic, routing: {step: strong|cheap}
prompt.md       # system prompt
tools/*.py      # each exposes TOOL = {name, description, input_schema} and run(input: dict) -> str
memory/         # rules.jsonl, tool_notes.jsonl, episodes.jsonl — see §0.2 (replaces the earlier flat memory.md)
```

Table `agents(agent_id, goal, domain, evaluator_id, current_version, created_ts)`. `current_version` is the only mutable pointer.

### 4.3 Evaluator — `contracts/evaluator.md`

```
evaluators/<evaluator_id>/
  README.md      # the domain, what "good" means, the tools the agent is allowed
  cases.jsonl    # {id, split: train|holdout, input: {...}, expected: {...}, tags: [...]}
  score.py       # def score(expected: dict, actual: dict) -> {"passed": bool, "score": float, "notes": str}
```

**Rule:** the improver may read train failures and their transcripts. **Holdout is never shown to the improver**; it is only run for reporting after an accepted fix.

### 4.4 Playbook — `contracts/playbook.md`

`playbook/lessons.jsonl`: `{id, lever, trigger, lesson, domain_tags[], source_agent_id, source_issue_id?, ts}`.
The architect reads the whole playbook when `use_playbook=true` and must record which lesson ids it applied.

### 4.5 REST API — `contracts/api.md` (frontend builds against this with mocks)

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

Internal Python signature workers code against: `improver.improve(agent_id: str, max_attempts: int = 3, issue_id: str | None = None) -> ImproveResult`.

---

## 5. Phase 0 — Scaffold (orchestrator does this directly, ~1.5h)

Deliver on `main`:

- Repo layout from §3; `Makefile` targets; `.env.example`.
- `contracts/` complete per §4 (pydantic models + markdown).
- `backend/db.py`: numbered migrations creating `events`, `agents`, `issues`, `lessons`, `improve_jobs`. Migrations are never edited after merge; add new ones.
- `backend/llm.py` with `complete(messages, model, tools=None) -> {text, tool_calls, usage, cost_usd}` and a fake-LLM test double in `backend/testing/fake_llm.py` that replays scripted responses (every worker uses this in tests).
- `backend/ledger/emit.py` stub that validates and inserts (W1 builds metrics on top).
- Frontend scaffold with Tailwind + Recharts and empty routes `/agents`, `/agents/[id]`, `/issues`, `/issues/[id]`, `/insights`.
- CI workflow. `BUILD_LOG.md` seeded.

**Acceptance:** `make test` green on the empty suite, `make dev` starts both servers, CI passes on `main`.

Then spawn **W1–W5 simultaneously**.

---

## 6. Phase 1 — Parallel foundations (5 workers, ~8h wall clock)

### [WORKER] W1 — Ledger & metrics service
**Owns:** `backend/ledger/`
- `emit(kind, **fields)` validates against §4.1, appends, never updates or deletes.
- `metrics.py`: pure functions over events — `pass_rate(agent_id, version, split) -> {mean, std, min, max}` computed from `case_result` rows grouped by `repeat` per §4.1, `stable_pass_set(agent_id, version)` (cases passing in every repeat), `cost_per_run`, `latency_percentiles`, `fixes_by_lever`, `regressions_caught`, `issue_stats`, `drift_stats(agent_id)` (count by kind, `tokens_saved` = sum of `DRIFT_TOKEN_BUDGET − tokens_at_detection` for aborts, cases recovered after a nudge), `series_by_version(agent_id)`, `markers(agent_id)` (issue/fix/drift events with version + lever + diagnosis for chart annotations).
- `fix_cards(agent_id) -> [FixCard]`: join `fix_proposed` ↔ `fix_accepted`/`fix_rejected` by `to_version`, attach `diff_url`. Pure function over events + the diff file on disk.
- Endpoints: `GET /events`, `GET /insights/{agent_id}`, `GET /insights/compare`, `GET /agents/{id}/fixes`, `GET /agents/{id}/fixes/{to_version}/diff`.
- Tests: seed a ledger fixture with `repeats=3` and a mix of flaky/stable cases → assert mean/std/min/max, the stable set, drift stats, and fix-card assembly; assert no derived value is ever written to any table.

**Acceptance:** with the seeded fixture, `/insights/{id}` returns correct series; metrics are provably pure functions of events.

### [WORKER] W2 — Agent runtime & eval harness
**Owns:** `backend/runtime/`
- Load a package version (§4.2), build the tool registry from `tools/*.py`, run the tool-use loop via `llm.py` for one case, return actual output + full transcript.
- **Harness-level observation (rule §2.8):** the loop itself records every request, response, tool call, tool return, token count (from the API usage field), and per-step timestamp into the transcript. The agent is never asked to summarize what it did. The transcript is the single source of truth for the drift watchdog, the failure analyst, and Neatlogs.
- Three orchestration modes: `single`, `planner_worker`, `generate_critic`. Each ≤60 lines; they share one loop.
- **Repeats:** `run_eval(agent_id, version, split, repeats=EVAL_REPEATS)` runs every case `repeats` times (different `repeat` index, same input, temperature as configured). Emit one `case_result` per (case, repeat). `run_finished` carries `pass_rate_mean/std/min/max` per §4.1. Transcripts at `runs/<run_id>/<case_id>.r<repeat>.json`.
- **Drift watchdog** (`backend/runtime/drift.py`), evaluated after every step of the loop, from observed transcript state only:
  - `loop`: the same tool called with the same normalized args `DRIFT_REPEAT_CALL_LIMIT` times → **nudge** once (inject a system message: "You have called `<tool>` with identical arguments N times. Change approach or answer with what you have."). A second trigger on the same case → **abort**.
  - `budget`: cumulative tokens for the case exceed `DRIFT_TOKEN_BUDGET` → **abort**.
  - `step_limit`: steps exceed `DRIFT_MAX_STEPS` → **abort**.
  - `off_task`: last two assistant messages contain none of the required output keys and no tool call → **nudge** with the expected output schema; abort on repeat.
  - Every trigger emits `drift_detected` with `evidence` (the concrete repeated call / counts) and `action`. An aborted case is scored as a failure with `failure_signature = "drift:<kind>"` so the improver can target it. A nudged case that then passes is counted as `cases_recovered_by_nudge`.
- `failure_signature`: normalized string from (score notes + first tool error + missing expected keys), so identical failures dedupe across runs.
- Bounded concurrency via semaphore, env `EVAL_CONCURRENCY` (default 4). Per-case wall-clock timeout, recorded as `drift_detected(kind=budget)` for accounting.
- `POST /agents/{id}/run` (background job; progress in `improve_jobs` or a sibling table).
- Tests: fake LLM with scripted tool calls; assert emitted events, pass/fail, transcript written, timeout handled. Add: fake LLM that repeats the same tool call forever → assert nudge then abort, `drift_detected` payloads, and `tokens_saved_by_drift` > 0. Add: repeats=3 with one flaky scripted case → assert `pass_rate_std` > 0 and the case is excluded from the stable set.

**Acceptance:** a hand-written toy package + 3-case evaluator runs end to end with the fake LLM at `repeats=3`, emits exactly the expected events including one `drift_detected`, and the transcript contains every tool call the fake LLM made.

### [WORKER] W3 — Architect (agent generator)
**Owns:** `backend/architect/`, `backend/toolbox/`
- `backend/toolbox/`: small reusable tool library — `html_to_text`, `regex_extract`, `date_parse`, `json_validate`, `number_parse`. All offline.
- `generate(goal, domain, tools[], evaluator_id, use_playbook)`, one STRONG-model call per step:
  1. read evaluator README + 5 sample train cases,
  2. choose orchestration mode with a one-paragraph justification,
  3. draft `prompt.md`,
  4. select tools from the toolbox and write any glue tool needed (with a unit test),
  5. write `agent.yaml`,
  6. if `use_playbook`, read `playbook/lessons.jsonl`, apply relevant lessons, record `applied_lessons`.
- Writes `agents/<id>/v0/`, inserts into `agents`, emits `agent_created`.
- Endpoints: `POST /agents`, `GET /agents`, `GET /agents/{id}`, `GET /agents/{id}/versions/{n}`, `GET /evaluators`.
- Tests: fake LLM; assert the package validates against contracts and loads via the §4.2 model (do **not** import W2 code; validate against contracts only).

**Acceptance:** `POST /agents` with a real LLM produces a v0 package that validates against `contracts/agent.py`.

### [WORKER] W4 — Domains, fixtures, evaluators
**Owns:** `evaluators/`, `fixtures/`, `scripts/validate_evaluators.py`
Both evaluators must be **deterministic and fully offline** (no live network in eval).

- **Domain A — `hackathon_extract`.** 40 *synthesized* hackathon listing HTML pages under `fixtures/hackathons/` (generate with a template script + hand-edited hard cases; do not copy real sites). Expected: `{name, start_date, end_date, submission_deadline, prize_total_usd, location_type, tracks[]}`. `score.py`: field-level match after normalization; `passed` iff all required fields match; `score` = fraction matched. Hard cases (tagged): dates in prose, multiple currencies, deadline ≠ end date, tracks in nested lists, missing prize, timezone suffixes.
- **Domain B — `ticket_triage`.** 50 synthetic support tickets under `fixtures/tickets/`. Expected: `{category ∈ {billing,bug,feature,account,other}, priority ∈ {p0,p1,p2,p3}, needs_human: bool}`. Hard cases (tagged): mixed language, sarcasm, multiple issues in one ticket, p0 signal buried at the end, angry-but-low-priority.
- **Headroom target:** a naive v0 agent should land at 40–60% on both. If a domain is too easy, add hard cases. We need room for the curve to climb.
- Split 70/30 train/holdout, stratified by tag. `tags` must describe the hard-case type so failure analysis can group by tag.
- `scripts/validate_evaluators.py` checks schema, split balance, and that an "always-empty" agent scores ~0.

**Acceptance:** both evaluators load, `score.py` has unit tests, validator passes.

### [WORKER] W5 — Frontend shell (against mock API)
**Owns:** `frontend/`
- `/agents`: list + "New agent" form (goal, domain, tools multiselect, evaluator select, use_playbook toggle).
- `/agents/[id]`: header (name, domain, current version); tabs Prompt / Tools / Memory / Runs / **Fixes**; buttons Run train, Run holdout, Improve; case results table grouped by case with a per-repeat pass strip (e.g. `✓ ✓ ✗`), score, cost, latency, trace link, transcript link, and a drift badge when any repeat emitted `drift_detected`; version switcher.
- **Fixes tab** renders `FixCard`s (§4.5) as a vertical timeline, newest first. Each card: status pill (accepted/rejected), lever chip, failing group (tag + count), hypothesis, before → after numbers with ± spread, files touched, and an expandable unified diff viewer (`react-diff-viewer-continued` or a simple `<pre>` with +/- coloring). Rejected cards list the regressed case ids. Build against mock cards now.
- `/issues`: list with filters (source, status); "New issue" (title, body, screenshot upload).
- `/issues/[id]`: body, screenshot, linked cases, fix timeline (proposed → accepted/rejected with lever + diagnosis).
- `/insights`: layout for the five charts in W9, rendered against mock series for now.
- Mock layer switched by `NEXT_PUBLIC_USE_MOCKS`; every fetch goes through `api.ts` matching §4.5 exactly.
- Design: minimal, dark, dense, no marketing copy. Every empty state says what action produces data.

**Acceptance:** all pages render with mocks, `next build` passes, `api.ts` mirrors §4.5.

**Phase 1 merge order:** W1 → W2 → W3 → W4 → W5. Resolve conflicts in that order. Then spawn Phase 2.

---

## 7. Phase 2 — The improvement loop (5 workers, ~9h wall clock)

### [WORKER] W6 — Failure analyst & improver (the core of Track 1)
**Owns:** `backend/improver/`
**Depends:** W1, W2, W3, W4 merged.
- `diagnose(agent_id, version)`: collect train `case_result` failures for the current version **across all repeats** (a case that failed 2 of 3 repeats is a failure with weight 2/3), group by `failure_signature` and evaluator `tags`, read the top-3 groups' transcripts, produce a ranked list of `{failing_group, hypothesis, lever, proposed_change}`. One STRONG call per group. `drift:*` signatures are a first-class group: the hypothesis for a `drift:loop` group is usually a tools or prompt fix (missing tool, ambiguous instruction), and the analyst must say which.
- `patch(agent_id, version, diagnosis)`: apply **exactly one lever** per attempt:
  - `prompt` → targeted edit of a section of `prompt.md` (diff, not full rewrite)
  - `tools` → add or modify one tool, generate and run a unit test for it
  - `memory` → append to `memory.md`
  - `orchestration` → change mode in `agent.yaml`
  Writes `agents/<id>/v<N+1>/` as a full snapshot, writes a unified diff of `v<N>` → `v<N+1>` to `agents/<id>/v<N+1>/CHANGES.diff`, emits `fix_proposed` with the full §4.1 payload (`failing_group`, `hypothesis`, `diff_path`, `files_touched`). **The fix card is only as good as this payload; do not skimp.** `diagnosis` must be ≤3 sentences in plain language a judge can read aloud.
- `gate(agent_id, candidate_version)`: run the full **train** set on the candidate at `EVAL_REPEATS`. Accept iff (a) every case in the prior version's **stable pass set** (§4.1) is still stably passing, and (b) `pass_rate_mean` ≥ prior `pass_rate_mean`. On accept: emit `fix_accepted` with before/after mean±std, the failing group's own pass rate before/after, and cost per run before/after; bump `current_version`; then run **holdout** once at `EVAL_REPEATS` and record it. On reject: emit `fix_rejected` with `regressed_case_ids` and the candidate's mean, then retry with the next-ranked diagnosis, preferring a different lever.
- `improve(agent_id, max_attempts=3, issue_id=None)`: loop diagnose → patch → gate. If `issue_id` is given, prioritize the diagnosis group linked to that issue's cases.
- `POST /agents/{id}/improve` as a background job with progress in `improve_jobs`; `GET /jobs/{id}`.
- Tests: fake LLM producing a known patch; assert the gate **rejects** a patch that regresses a seeded stably-passing case and accepts one that doesn't; assert a flaky case (passes 2/3) is *not* in the stable set and therefore cannot cause a false regression; assert `CHANGES.diff` is written and `fix_proposed.diff_path` points at it.

**Acceptance:** on Domain A with a real LLM, 5 improve iterations yield a non-decreasing train `pass_rate_mean`, holdout mean±std is recorded after each accept, `GET /agents/{id}/fixes` returns a complete card for every attempt, and the test suite contains a scenario producing `fix_rejected`.

### [WORKER] W7 — Issues
**Owns:** `backend/issues/`, real wiring of `/issues` and `/issues/[id]` in `frontend/`
**Depends:** W1, W2 merged. May start before W6 by coding against the `improver.improve` signature in §4.5.
- Table `issues(id, agent_id, title, body, screenshot_path, source, status, failure_signature, created_ts, fixed_version)`; `status ∈ {open, fixing, fixed, wontfix}`.
- **Human path:** `POST /issues` (multipart). On create, a CHEAP-model call drafts a regression case `{input, expected}` from body + screenshot description, appends it to the evaluator's **train** set with tag `from_issue:<id>`, emits `issue_opened` + `issue_linked_case`.
- **Auto path:** after every `run_finished`, group new failures by `failure_signature`; if no open issue has that signature, open one with `source=auto`, title derived from the signature, link all matching cases. Dedupe strictly — one issue per signature.
- `POST /issues/{id}/fix` → `improver.improve(agent_id, issue_id=id)`; on `fix_accepted` covering the linked cases, set `status=fixed`, `fixed_version`.
- Frontend: replace mocks; the issue's fix timeline is the subset of `GET /agents/{id}/fixes` whose `failing_group.case_ids` intersect the issue's linked cases, rendered with the same FixCard component as the agent's Fixes tab.
- Tests: filing an issue creates a train case; a run failing 3 cases with one signature opens exactly one auto issue; a second run does not duplicate it.

**Acceptance:** both paths work end to end against the real ledger.

### [WORKER] W8 — Playbook (cross-agent memory)
**Owns:** `backend/playbook/`, `playbook/`, `scripts/playbook_ablation.py`
**Depends:** W1, W3 merged; W6's `fix_accepted` payload stable.
- On every `fix_accepted`, a CHEAP-model call extracts one **general, domain-independent** lesson with a trigger condition. Emit `lesson_recorded`, append to `playbook/lessons.jsonl`. Skip near-duplicates (normalized string similarity ≥ 0.85; no embeddings).
- `GET /playbook`.
- Verify W3's `applied_lessons` is populated when `use_playbook=true`; add a test.
- `scripts/playbook_ablation.py`: create the Domain B agent twice — `use_playbook=false` and `use_playbook=true` — run holdout on both v0s, write `reports/ablation.json` with both pass rates and the applied lesson ids. **This is a demo artifact.**

**Acceptance:** after improving Domain A, `lessons.jsonl` has ≥3 lessons; the ablation script runs end to end.

### [WORKER] W9 — Insights (real charts)
**Owns:** `frontend/app/insights/`, run panels in `frontend/app/agents/[id]/`
**Depends:** W1 merged.
All charts read from `/insights` and `/agents/{id}/fixes`; nothing is hardcoded.
1. **Pass rate by version with error bars** — train and holdout as two lines, each with a shaded **mean ± std band** and min/max whiskers (Recharts `Area` for the band under the `Line`, `ErrorBar` for whiskers). Vertical markers for `issue_opened`, `fix_accepted`, `fix_rejected`, and `drift_detected` clusters; hover on a fix marker shows lever + hypothesis and links to its fix card. Subtitle states `repeats = N`.
2. **Cost per run** and **p50/p95 latency** by version, plus a **pass rate vs cost** scatter (one dot per version, arrows in version order) so the judge can see accuracy and cost moving together.
3. **Fixes by lever** (bar) + **regressions caught** (counter) + issues open/closed.
4. **Fix cards** — the same FixCard timeline as the agent's Fixes tab, embedded here for the selected agent, newest first, with the diff collapsed by default.
5. **Drift panel** — count by kind (loop/budget/step_limit/off_task), `tokens_saved`, `cases_recovered_by_nudge`, and drift count per version (it should fall as fixes land; if it doesn't, show that).
6. **Domain comparison** — Domain A and B pass-rate bands side by side, plus ablation numbers if `reports/ablation.json` exists.
7. **Playbook panel** — lessons with links to source agent and issue.

**Acceptance:** with a seeded ledger every chart renders including the band and whiskers; with an empty ledger every chart shows an honest empty state; every fix card's diff opens.

### [WORKER] W10 — Cost & speed lever (small; **cut first if behind**)
**Owns:** `backend/runtime/routing.py`
**Depends:** W2, W6 merged.
- Per-step model routing from `agent.yaml` (`routing: {plan: strong, extract: cheap, critique: strong}`).
- Static system prompt first for cache-friendliness.
- Improver gains pseudo-lever `routing`: try CHEAP for a step; accept only if the gate passes **and** `cost_per_run` drops.

**Acceptance:** one accepted routing fix on Domain B lowers cost with no pass-rate loss.

**Phase 2 merge order:** W6 → W7 → W8 → W9 → W10.

---

## 8. Phase 3 — Integration, evidence, demo (~7h; orchestrator + 2 workers)

### [WORKER] W11 — End-to-end runs & evidence
**Owns:** `scripts/demo_run.py`, `reports/`
- Script: create Domain A agent (`use_playbook=false`) → run train + holdout → `improve` ×6 → file one **human** issue via the API mid-way (scripted body + a screenshot from `fixtures/`) → fix it → run `playbook_ablation.py` for Domain B → `improve` Domain B ×4.
- Write `reports/domain_a.json`, `reports/domain_b.json`, `reports/ablation.json`, and `reports/summary.md` with headline numbers, **every pass rate stated as mean ± std at `repeats = N`**: v0→vN holdout pass rate per domain, cost delta, latency delta, fixes by lever, regressions caught, drift events by kind and `tokens_saved`, count of accepted vs rejected fix cards, lessons count, AO session count from `BUILD_LOG.md`.
- Include one full fix card verbatim in `summary.md` (the best-looking accepted one) so the README results section shows the mechanism, not only the curve.
- If any number is flat or negative, report it as-is and open a GitHub issue describing the likely cause.

**Acceptance:** `reports/summary.md` exists with real numbers from real runs; `make demo` reproduces it.

### [WORKER] W12 — README, setup, demo script
**Owns:** `README.md`, `DEMO.md`
- README: what it is; Mermaid architecture diagram; the four-step loop (generate → run → analyze → improve) mapped to modules; setup in ≤10 commands; env vars; **How AO was used** section linking `BUILD_LOG.md`; evaluation method (train/holdout, gate rules); results table copied from `reports/summary.md`; Neatlogs usage.
- `DEMO.md`: the §9 shot list with exact clicks and URLs.

**Acceptance:** fresh clone → README steps → `make dev` works.

**Orchestrator:** final integration pass, tag `v0.1.0`, confirm `BUILD_LOG.md` lists every session with PR links.

---

## 9. Demo video shot list (≈3 min)

**Superseded by §0.6.** The shots below are still valid material; use §0.6's order and emphasis. Key rule from the judge: plan this early, do not record it in the last hour.

1. **(15s)** AO board showing all worker sessions and PRs; flash `BUILD_LOG.md`. *(AO-usage evidence.)*
2. **(30s)** New agent form: goal + tools + evaluator → v0 generated. Show `prompt.md` and the chosen orchestration mode with its justification.
3. **(20s)** Run train at `repeats=3`: results table filling with per-repeat pass strips; point at one flaky case; open one failure's Neatlogs trace. Show a **drift badge** and its `drift_detected` evidence (the repeated tool call).
4. **(35s)** Improve: open the **fix card** — failing group, hypothesis, lever, expand the diff, before → after with ± spread. Show one **rejected** card (regression caught, regressed case ids listed), then an accepted one. Read the hypothesis aloud.
5. **(20s)** File a human issue with a screenshot → regression case appears in the train set → fix → issue closed, its fix card attached.
6. **(30s)** Insights: pass-rate band with whiskers and markers, pass-rate-vs-cost scatter, fixes by lever, drift panel with `tokens_saved`.
7. **(20s)** Domain B: ablation numbers (playbook on vs off), then its own band. *"Tasks it has never seen before."*
8. **(10s)** Results table (all numbers with ±), repo link.

---

## 10. Time budget (30h) and cut order

| Window | Work |
|---|---|
| 0–1.5h | Phase 0 (orchestrator) |
| 1.5–10h | Phase 1, W1–W5 in parallel |
| 10–19h | Phase 2, W6–W10 in parallel |
| 19–26h | Phase 3, W11–W12 + integration |
| 26–30h | Buffer, video, Devpost submission |

**Cut order if behind:** W10 → pass-rate-vs-cost scatter → domain comparison side-by-side (keep ablation numbers as text) → drift `nudge` action (keep detection + abort; that is still a chart) → `off_task` drift kind (keep loop/budget/step_limit) → `generate_critic` mode → screenshot upload (keep text-only issues) → Domain B improve iterations (keep the ablation) → reduce `EVAL_REPEATS` to 2 (never 1; the band must exist).

**Never cut:** repeats ≥ 2, the fix card payload in `fix_proposed`/`fix_accepted`, the regression gate, `BUILD_LOG.md`.

---

## 11. Kickoff

Orchestrator: acknowledge this plan by writing the Phase 1 dependency graph and your session id into `BUILD_LOG.md`, execute Phase 0, open a PR for it, merge it, then spawn **W1, W2, W3, W4, W5 in parallel** with each worker's block from §6 as its task description plus a pointer to §2, §3, and §4 of this file.
