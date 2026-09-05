# Transcript contract

Source of truth: `contracts/transcript.py`. **Frozen after Phase 0.**

The transcript is the harness-level record of **what the agent actually did**.
It is written by the runtime loop (W2) at the point where each thing happens —
never assembled afterwards from the agent's own account of itself. This is
PLAN.md rule §2.8 made concrete: the drift watchdog, the failure analyst, the
reflection step and Neatlogs all read *this file*, and none of them may ask the
agent what it did.

## Path

One file per (task, trial):

```
runs/<run_id>/<case_id>.t<trial>.json
```

Build it with `contracts.transcript.transcript_path(run_id, case_id, trial)`,
not by hand. `case_result.transcript_path` points at this file. Trial
isolation (section J): each trial gets its own transcript, starting from a
clean message list -- a trial never sees another trial's transcript or the
improver's diagnoses.

## Shape

```json
{
  "run_id": "r_12",
  "case_id": "issue_412",
  "trial": 0,
  "agent_id": "a_github_triage",
  "version": 3,
  "started_ts": "2026-09-06T11:20:04Z",
  "finished_ts": "2026-09-06T11:20:11Z",
  "steps": [
    {"i": 0, "ts": "...", "kind": "request",     "model": "gpt-4o", "messages": [...]},
    {"i": 1, "ts": "...", "kind": "response",    "model": "gpt-4o", "text": "",
     "tokens_in": 1840, "tokens_out": 42},
    {"i": 2, "ts": "...", "kind": "tool_call",   "tool": "get_issue", "args": {"number": 412}},
    {"i": 3, "ts": "...", "kind": "tool_return", "tool": "get_issue", "result": "{...}"},
    {"i": 4, "ts": "...", "kind": "nudge",       "text": "You have called `get_issue` with identical arguments 3 times. ..."}
  ],
  "final_output": {"labels": ["bug", "platform:windows"], "component": "pty"},
  "tokens_in": 4210,
  "tokens_out": 260,
  "tool_calls": 4,
  "tool_errors": 1,
  "rules_injected": ["rule_1a2b3c", "rule_9f0e"],
  "drift": [{"kind": "loop", "step": 4, "action": "nudge"}]
}
```

### Fields

| field | meaning |
|---|---|
| `run_id`, `case_id`, `trial` | identify the file; `trial` is 0-based, `0..trials-1` |
| `agent_id`, `version` | the exact package snapshot that produced this |
| `started_ts`, `finished_ts` | ISO8601 UTC, wall clock measured by the harness |
| `steps[]` | every observed step, in order, `i` starting at 0 |
| `final_output` | the parsed object handed to `score.py`, or `null` if the agent produced nothing parseable (a drift abort, a malformed answer) |
| `tokens_in` / `tokens_out` | totals from the API usage fields, summed over `response` steps |
| `tool_calls` / `tool_errors` | counts over `tool_call` / `tool_return` steps; these are the same numbers `case_result` carries |
| `rules_injected[]` | `MemoryRule.id`s the **runtime** injected for this case — written by the runtime, never by the agent (§0.2) |
| `drift[]` | one entry per watchdog trigger, mirroring the `drift_detected` events |

### Step kinds

| `kind` | fields set |
|---|---|
| `request` | `model`, `messages` — exactly what was sent |
| `response` | `model`, `text`, `tokens_in`, `tokens_out` |
| `tool_call` | `tool`, `args` |
| `tool_return` | `tool`, and `result` **or** `error` |
| `nudge` | `text` — the system message the watchdog injected |

Steps carry `extra="allow"`, so a worker may attach more observed detail
(latency, cache hit, retry count) without a contract change. Nothing derived
and nothing self-reported belongs here.

### Consistency

`case_result` must agree with its transcript: `tokens_in`, `tokens_out`,
`tool_calls`, `tool_errors`, `rules_injected[]` and `steps` are the same
numbers on both sides. If they disagree, the transcript is right — it is the
observation, `case_result` is the summary.

## Python API

```python
from contracts.transcript import Transcript, load_transcript, transcript_path

t = Transcript(run_id="r_12", case_id="issue_412", trial=0, agent_id="a1",
               version=3, started_ts=..., finished_ts=...)
path = t.write()                 # runs/r_12/issue_412.t0.json
same = load_transcript(path)
```

---

# Per-case tool context

Source of truth: `contracts/context.py`.

`current_case` is a `ContextVar[dict | None]` (default `None`). The runtime sets
it to the evaluator case dict before running each case and resets it after, so
a tool can see which case it is serving without threading it through every call
signature:

```python
from contracts.context import current_case, case_scope

# runtime (W2)
with case_scope(case):
    ...  # run the tool-use loop for this case

# tool (W3 toolbox)
def run(input: dict) -> str:
    case = current_case.get()
    target = (case or {}).get("input", {}).get("number")
    ...
```

**Why it exists:** the `github_triage` tools fetch data about an issue whose
ground-truth labels *are* the expected answer. A tool must redact those before
returning, or the agent reads the answer straight off the tool output and every
score is meaningless. `current_case` is how a tool knows what to redact.

Rules:

1. Only the runtime writes it, once per case, via `case_scope`.
2. A `ContextVar` is per-task, so it is safe under `EVAL_CONCURRENCY`.
3. A tool must tolerate `None` — that is the value outside a case (for example
   when the architect smoke-tests a freshly generated tool).
4. It carries the **case**, nothing else. It is not a memory channel, and it is
   not a way for a tool to report what it did (rule §2.8).
