# Build log

Demo evidence of AO usage: every AO session, branch, PR, outcome.

## Orchestrator session

| | |
|---|---|
| Session | `task-orchestrator-3` |
| Branch | `ao/task-orchest-orchestrator` |
| Started | 2026-09-05T18:45Z |

## Dependency graph

**Phase 0** — W0 scaffold (contracts, db, llm, ledger stub, frontend shell, CI)
→ merges to `main` before any Phase 1 worker spawns.

**Phase 1** — spawned simultaneously once Phase 0 is on `main`:

- W1 — ledger & metrics
- W2 — agent runtime & eval harness
- W3 — architect + toolbox (github)
- W4 — domains (`github_triage`, `ticket_triage`)
- W5 — frontend shell

Merge order: **W1 → W2 → W3 → W4 → W5.**

**Phase 2** — spawned after Phase 1 merges:

- W6 — improver (needs W1–W4)
- W7 — issues (needs W1, W2)
- W8 — playbook (needs W1, W3, and W6's payload)
- W9 — insights (needs W1)
- W10 — routing (needs W2, W6; **cut first** if time runs short)

**Phase 3** — W11 evidence, W12 README/DEMO.

## Decisions — 2026-09-05 19:10Z (orchestrator session task-orchestrator-3)

**Time check (§M):** deadline Sunday 2026-09-06 18:00 EDT = 22:00 UTC. Remaining at check time: **26 h 54 m**. More than 10 h remain, so the full plan applies: §B, §D, §E, §F, §G, §J, §K all in scope. Nothing cut yet. Cut order if behind, per §M: W10 → off_task drift → pass-vs-cost scatter → side-by-side domain comparison → drift nudge → generate_critic (already dropped) → Domain B improve iterations → trials to 2.

**PLAN_ADDENDUM.md** is the source of truth over PLAN.md. It is stored at `C:/Users/manuj/.ao/briefs/task-orchestrator/PLAN_ADDENDUM.md` for live workers and lands on `main` via a doc-only PR (W0b).

**§L reconciliation.** No workstream was merged at check time, so no `W<n>b` follow-ups were needed for merged work.

| Workstream | State at check | Decision |
|---|---|---|
| W0 scaffold (task-orchestrator-4) | in progress, contracts drafted, unpushed | kept; §A contract changes routed to W0's PR (owns `contracts/`) |
| W0b addendum doc (task-orchestrator-10) | not started | spawned; PR #2 merged to main at 19:15Z as eba2a1c (`PLAN_ADDENDUM.md` + one-line pointer in `PLAN.md`) |
| W1 ledger (task-orchestrator-7) | in progress (started early on pure metrics) | kept; messaged with deltas (pass@1 / pass^k, tool_call_stats, graduation, saturation) |
| W2 runtime (task-orchestrator-8) | in progress (started early on drift/memory/signature) | kept; messaged with deltas (trials, isolation, task_graduated, drift order) |
| W3 architect + toolbox (task-orchestrator-9) | in progress (toolbox first) | kept; messaged: seven thin wrappers replaced by the four consolidated `github_*` tools |
| W4 evaluators (task-orchestrator-5) | in progress, draft PR #1 | kept; messaged: reference_output, negatives, four tool names, validator assertion |
| W5 frontend (task-orchestrator-6) | in progress | kept; messaged: §A shapes, pass@1/pass^k copy, grader-disagreed button, graduated/saturation slots |
| W6 improver | not started | will spawn after Phase 1 merges with PLAN.md block + addendum (§E reflection first, §K tools lever, gate on pass^k) |
| W7 issues | not started | will spawn after W1, W2 merge; text-only, grader-bug path |
| W8 playbook | not started | unchanged; spawn after W1, W3 |
| W9 insights | not started | spawn after W1; §B chart, memory growth, tool efficiency, graduated counter, saturation banner |
| W10 routing | not started | shrunk to per-step model field + one measured routing change; first on the cut list |
| W11 evidence, W12 README/DEMO | not started | spawn in Phase 3; every pass rate as pass@1 and pass^k with ± |

**Domain decision:** `hackathon_extract` was never started (W4 was briefed on `github_triage` + `ticket_triage` from the outset), so Domain B stays `ticket_triage`.

Stall (22:23Z update): the shared account usage limit paused the orchestrator and all six worker sessions from roughly 19:20Z to 22:20Z. Remaining at 22:23Z: 23 h 36 m. Still above the 10 h threshold; scope unchanged.

**W3 note (PR #9 review):** `applied_lessons` cannot live in `agent.yaml` -- `AgentConfig` is `extra="forbid"` and does not define the field. It is recorded on the `agent_created` ledger event only (which does define it); `GET /agents/{id}` and `/versions/{n}` should read it from there rather than expecting it on the package.

## Sessions

| session id | workstream | branch | PR | outcome | started | finished |
|---|---|---|---|---|---|---|
| `task-orchestrator-4` | W0 — Phase 0 scaffold | `ws/w0-scaffold` | [#3](https://github.com/mikelord007/Task-Orchestrator/pull/3) | merged (a14dbd5) | 2026-09-06 | 2026-09-05 22:40Z |
| `task-orchestrator-10` | W0b — addendum doc (`PLAN_ADDENDUM.md`) | `ws/w0b-addendum` | #2 | merged (eba2a1c) | 2026-09-05 | 2026-09-05 |
| `task-orchestrator-7` | W1 — ledger & metrics | `ws/w1-ledger` | [#7](https://github.com/mikelord007/Task-Orchestrator/pull/7) | merged (1f9df25) | 2026-09-05 | 2026-09-05 22:52Z |
| `task-orchestrator-7` | W1b — since= id cursor, normalized_args/tokens_estimated, metric_signal gate | `ws/w1b-since-cursor` | [#11](https://github.com/mikelord007/Task-Orchestrator/pull/11) | merged (e26ba8f) | 2026-09-05 | 2026-09-06 01:15Z |
| `task-orchestrator-8` | W2 — agent runtime & eval harness | `ws/w2-runtime` | [#10](https://github.com/mikelord007/Task-Orchestrator/pull/10) | merged (f92cdc5) | 2026-09-05 | 2026-09-06 |
| `task-orchestrator-8` | W2b — cleanup: passed_by_trial padding, request-step message deltas, single-key tool_return, env knobs | `ws/w2b-cleanup` | [#14](https://github.com/mikelord007/Task-Orchestrator/pull/14) | ready for review (CI pending) | 2026-09-06 | 2026-09-06 |
| `task-orchestrator-9` | W3 — architect + toolbox | `ws/w3-architect` | [#9](https://github.com/mikelord007/Task-Orchestrator/pull/9) | merged (0af397a) | 2026-09-05 | 2026-09-06 |
| `task-orchestrator-9` | W3b — contract-change: `orchestration_reason` | `ws/w3b-contract-orchestration-reason` | [#8](https://github.com/mikelord007/Task-Orchestrator/pull/8) | merged (1c5285f) | 2026-09-06 | 2026-09-06 |
| `task-orchestrator-5` | W4 — domains, fixtures, evaluators | `ws/w4-domains` | [#1](https://github.com/mikelord007/Task-Orchestrator/pull/1) | merged (45676a9) | 2026-09-05 | 2026-09-05 |
| `task-orchestrator-5` | W4b — github_triage negatives follow-up | `ws/w4b-negatives` | [#6](https://github.com/mikelord007/Task-Orchestrator/pull/6) | ready for review (CI green) | 2026-09-05 | 2026-09-05 |
| `task-orchestrator-6` | W5 — frontend shell | `ws/w5-frontend` | [#4](https://github.com/mikelord007/Task-Orchestrator/pull/4) | merged (5bb748a) | 2026-09-05 | 2026-09-06 |
| `task-orchestrator-12` | W8 — playbook + Domain B ablation | `ws/w8-playbook` | [#13](https://github.com/mikelord007/Task-Orchestrator/pull/13) | draft, tests green locally | 2026-09-06 | — |
