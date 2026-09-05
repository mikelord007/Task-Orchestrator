# Task Orchestrator

Given a goal, a set of tools and an evaluator, Task Orchestrator generates a
specialized agent, runs it against the evaluator with every case repeated so
pass rates carry error bars, diagnoses where it fails, and improves it along
four levers — memory, tools, prompt, orchestration — gating every change so
regressions are rejected. Every outcome is appended to an event ledger; every
chart is a query over that ledger, so nothing on screen is a number someone
typed in. Lessons from improving one agent are distilled into a playbook the
next agent, in a different domain, starts from.

> Phase 0 scaffold. The contracts, database, LLM access, ledger writer, CI and
> the frontend shell are in place; the runtime, architect, evaluators, improver
> and the real pages land in Phase 1–3. See `PLAN.md`.

## Setup

```bash
cp .env.example .env          # fill in LLM_API_KEY (and GITHUB_TOKEN for github_triage)
make install                  # uv sync --project backend + npm ci in frontend/
make dev                      # backend :8000, frontend :3000
```

`make` is not installed on the Windows dev host. Equivalent commands:

| task | make | Windows |
|---|---|---|
| both servers | `make dev` | `pwsh scripts/dev.ps1` |
| tests | `make test` | `pwsh scripts/test.ps1` |
| lint | `make lint` | `pwsh scripts/lint.ps1` |

Or run them raw from the repo root:

```bash
uv sync --project backend
uv run --project backend python -m uvicorn backend.app:app --reload --port 8000
uv run --project backend python -m pytest backend/tests
uv run --project backend ruff check backend contracts scripts
cd frontend && npm ci && npm run dev
```

Health check: `curl http://localhost:8000/healthz`.

## Layout

```
backend/      FastAPI app, SQLite migrations, llm.py, ledger/, runtime/, architect/, improver/
contracts/    frozen contracts every workstream builds against
frontend/     Next.js 15 app router + Tailwind + Recharts
evaluators/   <evaluator_id>/{README.md, cases.jsonl, score.py}
agents/       <agent_id>/v<N>/ immutable agent package snapshots
fixtures/     evaluator inputs and the cached third-party tool responses
playbook/     lessons.jsonl — cross-domain transfer
runs/         transcripts and the SQLite ledger (gitignored)
reports/      generated reports, e.g. ablation.json (gitignored)
```

Start with `contracts/` — `events.py` (the ledger), `agent.py` +
`agent_package.md` (what an agent version is), `evaluator.md`, `playbook.md`,
`api.md`. They are frozen after Phase 0: a change needs an issue labelled
`contract-change`.

## Environment variables

| var | default | what for |
|---|---|---|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | — | required for live model calls |
| `LLM_MODEL_STRONG` | `gpt-4o` | architect, diagnosis, reflection |
| `LLM_MODEL_CHEAP` | `gpt-4o-mini` | routed steps |
| `LLM_COST_TABLE` | built-in | JSON override of USD per 1M tokens per model |
| `NEATLOGS_API_KEY` | — | optional tracing; transcripts are always written locally |
| `GITHUB_TOKEN` | — | read-only PAT for the `github_triage` tools |
| `TO_DB_PATH` | `runs/to.sqlite3` | SQLite ledger path |
| `EVAL_REPEATS` | `3` | runs per case — this is what produces the error bars |
| `EVAL_CONCURRENCY` | `4` | bounded parallelism during eval |
| `DRIFT_MAX_STEPS` | `12` | drift watchdog: step limit |
| `DRIFT_TOKEN_BUDGET` | `20000` | drift watchdog: per-case token budget |
| `DRIFT_REPEAT_CALL_LIMIT` | `3` | drift watchdog: identical tool calls before a nudge |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | frontend → backend |
| `NEXT_PUBLIC_USE_MOCKS` | `false` | frontend mock layer |

## Build process

Built with [AO](https://github.com/Untrivial-ai/agent-orchestrator): one worker
session per workstream, one branch and PR each. `BUILD_LOG.md` records every
session, branch, PR and outcome.
