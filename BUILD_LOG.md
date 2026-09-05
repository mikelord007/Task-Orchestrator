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

## Sessions

| session id | workstream | branch | PR | outcome | started | finished |
|---|---|---|---|---|---|---|
| `task-orchestrator-4` | W0 — Phase 0 scaffold | `ws/w0-scaffold` | _(pending)_ | in progress | 2026-09-06 | — |
