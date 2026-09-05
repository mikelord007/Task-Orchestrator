# Agent package contract

Source of truth: `contracts/agent.py`. This file documents the layout and the
Phase 0 readings of PLAN.md §4.2 / §0.2 / §0.4. **Frozen after Phase 0.**

## Layout

Every agent version is an immutable directory snapshot. Nothing inside `v<N>/`
is ever edited after the version is created; the improver writes `v<N+1>/`.

```
agents/<agent_id>/v<N>/
  agent.yaml
  prompt.md
  tools/
    <tool>.py          # TOOL = {name, description, input_schema}; run(input: dict) -> str
  memory/
    rules.jsonl
    tool_notes.jsonl
    episodes.jsonl
```

The only mutable pointer is `agents.current_version` in SQLite.

## `agent.yaml`

```yaml
name: github_triage_v0
version: 0
domain: github_triage
model_strong: gpt-4o
model_cheap: gpt-4o-mini
tools: [list_issues, get_issue]
orchestration: single          # single | planner_worker
routing:                       # step name -> strong | cheap
  planner: strong
  worker: cheap
```

- `orchestration` is `single` or `planner_worker`. **`generate_critic` is
  dropped** per §0.4 — do not add it back without a contract change.
- `routing` keys are free-form step names owned by the orchestration mode; only
  the value domain (`strong` / `cheap`) is fixed by the contract. An empty map
  means "use `model_strong` for every step".
- Unknown keys are rejected (`extra="forbid"`) so a typo in a generated
  `agent.yaml` fails loudly at load time.
- Every name in `tools` must be exposed by some `tools/*.py`, otherwise the
  package is invalid.

## `prompt.md`

The system prompt, plain markdown. Must be non-empty. Memory is **not** baked in
here — the runtime injects it per case (see below).

## `tools/*.py`

Each module must define exactly:

```python
TOOL = {
    "name": "get_issue",
    "description": "Returns the issue title, body, labels and state for one "
                   "issue number. Use before proposing labels. Does NOT return "
                   "comments -- call list_issue_comments for those.",
    "input_schema": {
        "type": "object",
        "properties": {"number": {"type": "integer"}},
        "required": ["number"],
    },
}


def run(input: dict) -> str:
    ...
```

- `run` returns a **string** (the tool result the model sees). Structured
  results are JSON-dumped by the tool itself.
- `input_schema` is a JSON Schema object, passed to the model as the tool
  parameter schema.
- Files starting with `_` are ignored (helpers).
- Tool descriptions follow Anthropic's "writing tools for agents" guidance:
  what it returns, when to use it, what it does *not* do.
- Loading a package **imports and executes** these modules. Packages are locally
  generated artifacts, not untrusted input.

## `memory/` (§0.2)

Structured, self-written, self-correcting. Replaces the earlier flat `memory.md`.

`rules.jsonl` — `MemoryRule`:

```json
{"id": "rule_1a2b3c", "rule": "ConPTY / Windows terminal reports get label `platform:windows`",
 "scope_keywords": ["conpty", "windows", "terminal"], "evidence_case_ids": ["issue_412", "issue_455"],
 "confidence": 0.7, "hits": 0, "misses": 0, "created_version": 1,
 "source": "reflection", "demoted": false}
```

`tool_notes.jsonl` — `ToolNote`:

```json
{"id": "note_9f8e", "tool": "list_issues",
 "note": "paginates at 100; pass state=all when hunting duplicates",
 "evidence": "run r_12 case issue_331: page 2 held the duplicate",
 "created_version": 1}
```

`episodes.jsonl` — `Episode`:

```json
{"id": "ep_44", "run_id": "r_12", "case_id": "issue_331", "version": 1,
 "text": "Missed the duplicate because list_issues defaulted to state=open."}
```

### Rules the runtime and improver must honour

1. **Injection (W2).** Before each case, inject **all** `tool_notes` plus the
   top-K `rules` by keyword overlap between `scope_keywords` and the case input
   (**K = 12**, no embeddings). Demoted rules are never injected.
2. **Credit (W2).** After `score.py` returns, credit `hits`/`misses` on the
   rules that were injected for that case. `rules_injected[]` in `case_result`
   is written **by the runtime**, never by the agent.
3. **Demotion (W2).** A rule with `misses > hits` after **≥ 4 uses**
   (`hits + misses >= 4`) is demoted: `demoted = true`, kept on disk, no longer
   injected, and `memory_demoted` is emitted.
4. **Reflection (W6).** Proposals only. Inputs are the harness-recorded
   transcript, the tool data the agent saw, and the `score.py` verdict. The
   reflection prompt must contain the line: *"Do not evaluate your own
   performance; the grade is given. Explain the discrepancy using only the
   transcript and tool data provided."* Accepted proposals go through the gate
   as `lever = memory` and emit `memory_written`.
5. **Empty is valid.** A v0 package starts with empty (or absent) memory files.
   Absence loads as an empty list; a malformed line is a load error.

## Python API

```python
from contracts.agent import load_package, validate_package

errors = validate_package("agents/a1/v0")   # -> list[str], empty means valid
pkg = load_package("agents/a1/v0")          # -> AgentPackage, raises PackageError

pkg.config.orchestration     # "single"
pkg.prompt                   # str
pkg.tools["get_issue"].run({"number": 412})  # -> str
pkg.memory.active_rules      # rules eligible for injection
```

`new_entry_id("rule")` produces the `rule_<hex12>` id format used above.
