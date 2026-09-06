# Playbook scan and ablation contract

The playbook turns accepted fixes from one agent into domain-independent
lessons that a later agent can apply. `playbook/lessons.jsonl` remains the
append-only source of truth described by `contracts/playbook.md`.

## Scanning accepted fixes

Production callers should use the one-line hook exported by this package:

```python
from backend.playbook import scan_and_record

result = scan_and_record(conn)
```

Its exact signature is:

```python
def scan_and_record(
    conn: sqlite3.Connection, since_event_id: int | None = None
) -> dict[str, int]
```

The return value has this shape:

```text
{"recorded": int, "skipped": int, "last_event_id": int}
```

- `recorded` is the number of lessons appended during this call.
- `skipped` is the number of new `fix_accepted` events that did not append a
  lesson, including duplicates, unusable model output, and events without a
  matching `fix_proposed`.
- `last_event_id` is the persisted, exclusive event cursor.

With `since_event_id=None`, the helper resumes from the watermark in the
database's `playbook_scan_state` table. It persists the returned watermark
only after `scan()` finishes, so an interrupted scan is retried. Passing an
explicit event id can seed or advance the watermark, but cannot rewind stored
state. Use the lower-level `scan()` API when deliberately replaying older
events or when the caller needs to own its own watermark.

The helper writes to `TO_PLAYBOOK_PATH` when set, otherwise to
`<repo>/playbook/lessons.jsonl`. Repeated calls against the same database are
incremental and do not extract or record the same accepted fix again.

The lower-level contract remains:

```python
def scan(
    conn: sqlite3.Connection,
    *,
    since_event_id: int = 0,
    playbook_path: str | Path = DEFAULT_PLAYBOOK_PATH,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> ScanResult
```

`scan()` processes `fix_accepted` events whose ids are strictly greater than
`since_event_id`, in ledger order. Its `ScanResult` contains the appended
lesson rows, duplicate and unusable event-id lists, and `last_event_id`. That
cursor advances past every examined accepted fix, including skipped fixes.
Unlike `scan_and_record()`, `scan()` never saves the cursor; its caller must
pass the returned `last_event_id` into the next call.

## Duplicate threshold

Before appending, the recorder lowercases and collapses whitespace in the
combined `trigger` and `lesson`, then compares it with every existing lesson
using `difflib.SequenceMatcher`. A similarity ratio greater than or equal to
**0.85** is a near-duplicate and is skipped. There are no embeddings or model
calls in this dedupe step.

## Domain B ablation report

`scripts/playbook_ablation.py` writes `reports/ablation.json` with the following
shape (the metric values and ids are derived from the run, not supplied by this
documentation):

```text
{
  "domain": string,
  "trials": integer,
  "playbook_off": {
    "pass_at_1": number | null,
    "pass_pow_k": number | null,
    "std": number | null
  },
  "playbook_on": {
    "pass_at_1": number | null,
    "pass_pow_k": number | null,
    "std": number | null
  },
  "applied_lesson_ids": [string, ...],
  "agent_ids": {
    "playbook_off": string,
    "playbook_on": string
  }
}
```

Both arms create a fresh Domain B (`ticket_triage`) v0 agent with the same
goal, evaluator, tools, models, holdout split, and trial count. The only
intended difference is `use_playbook=false` versus `use_playbook=true`.
`applied_lesson_ids` comes from the playbook-on agent's `agent_created` event.
A flat or negative result is retained as observed.
