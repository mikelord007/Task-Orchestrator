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
    conn: sqlite3.Connection,
    *,
    since_event_id: int | None = None,
    playbook_path: str | Path = DEFAULT_PLAYBOOK_PATH,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> ScanResult
```

It returns the existing `ScanResult` dataclass:

```text
ScanResult(
    lessons: list[dict],
    skipped_duplicate_event_ids: list[int],
    skipped_unusable_event_ids: list[int],
    last_event_id: int,
)
```

- `lessons` contains the lesson rows appended during this call.
- `skipped_duplicate_event_ids` identifies accepted fixes whose extracted
  lesson was already represented in the playbook.
- `skipped_unusable_event_ids` identifies accepted fixes whose model output
  could not produce a valid lesson.
- `last_event_id` is the scan's exclusive event cursor; a successful helper
  call persists it monotonically.

With `since_event_id=None`, the helper resumes from the watermark in the
database's `playbook_scan_cursors` table. An explicit event id overrides that
starting point for the call. The stored cursor advances only after `scan()`
returns successfully, so an interrupted scan is retried, and the cursor never
moves backward.

Migration `0002_playbook_scan_cursor.sql` creates the cursor table. This table
stores a **processing cursor**, not derived agent status or a cached metric: it
is operational bookkeeping in the same category as `schema_migrations`.
Evaluation and display state remain derived exclusively from the append-only
ledger. Repeated calls against the same database are incremental and do not
extract or record the same accepted fix again.

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
