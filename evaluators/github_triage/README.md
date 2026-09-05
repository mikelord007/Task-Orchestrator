# `github_triage`

Triage a real GitHub issue the way this repository's maintainers actually triage it.

The corpus is 60 **closed** issues from [`Untrivial-ai/agent-orchestrator`](https://github.com/Untrivial-ai/agent-orchestrator)
— the AO project itself. Ground truth is what the maintainers really applied before
closing: their labels, their component labels, their priority, their assignee.

This is the eval suite with **third-party tool access**. The agent is not handed the
repo's conventions; it has to discover them by reading *other* issues through the
GitHub tools and generalizing.

## The task

Each task in `cases.jsonl` has an `id`, a `split`, an `input`, an `expected` answer,
a `reference_output`, and `tags`. (The file name and the `id`/`case_id` field names
are part of the contract and stay as-is; everywhere else this README says "task,"
not "case.")

**Input** (`input`) — never contains any part of the answer:

```json
{
  "issue_number": 4471,
  "title": "...",
  "body": "...",
  "author": "...",
  "created_at": "2026-08-27T10:11:12Z",
  "repo": "Untrivial-ai/agent-orchestrator"
}
```

**Expected output** (`expected`), which is also the JSON shape the agent must produce:

```json
{
  "labels": ["bug", "needs-triage"],
  "component": ["comp/daemon"],
  "priority": "P1",
  "assignee": "illegalcall",
  "duplicate_of": null
}
```

| field | meaning |
|---|---|
| `labels` | every label the maintainers applied **except** `comp/*` and `P0`/`P1`/`P2`, sorted |
| `component` | the `comp/*` labels, sorted (a list — issues can span components) |
| `priority` | `"P0"`, `"P1"`, `"P2"`, or `"none"` when the maintainers set none |
| `assignee` | the assignee's login, or `null` |
| `duplicate_of` | issue number parsed from a closing comment (`duplicate of #N` / `dup of #N`), else `null` |

Only `labels`, `component` and `priority` are graded. `assignee` and `duplicate_of`
are recorded so the improver and the memory store have something to learn *about*
(who owns what, how duplicates get closed) without those guesses costing score.

`reference_output` is a copy of `expected`, shaped exactly like the agent's required
output — a concrete answer that is known to pass the grader. It exists so
`scripts/validate_evaluators.py` can prove every task is winnable *before* a run,
rather than discovering a broken task only after an agent stalls at 0% on it.

## What "good" means

The grader (`score.py`) is deterministic, offline, stdlib-only:

- `labelF1` — set F1 over `labels`; both sides empty scores 1.0.
- `component` — 1.0 iff the `component` **sets** are equal, else 0.0. A bare string
  is accepted as a one-element list.
- `priority` — 1.0 iff equal case-insensitively; a missing `priority` in the agent's
  output is read as `"none"`.
- **`passed`** iff `labelF1 >= 0.8` **and** `component` is exact.
- **`score`** = `0.5·labelF1 + 0.3·component + 0.2·priority`.
- A non-dict / missing output scores 0 with `notes = "no_output"`.

`notes` uses a fixed vocabulary so the runtime's `failure_signature` and the
improver's failure grouping stay stable across runs:
`missing_label:<name>`, `extra_label:<name>`, `component_mismatch`,
`priority_mismatch`, `no_output`, `ok` — sorted and `;`-joined.

**Headroom.** A constant guess of `{"labels":["bug"],"component":["comp/daemon"],"priority":"none"}`
scores a 30% pass rate / 0.647 mean. An empty output scores 0.137 mean and never
passes. That leaves the curve room to climb.

## Allowed tools

Backed by `backend/toolbox/github.py`: four consolidated tools (not one wrapper per
REST endpoint), cache-through to `fixtures/github_cache/` so eval runs are offline
and deterministic:

| tool | returns | use when |
|---|---|---|
| `github_get_issue_context(issue_number, response_format="concise"\|"detailed")` | title, body, author, comments, and any linked PRs/commits with the files they touched, in one call | you need everything known about one issue |
| `github_search_similar_issues(query, state="all", limit=10)` | candidate matches: title, labels, state, a two-line summary each | hunting for duplicates or recurring symptoms |
| `github_get_label_taxonomy()` | every label with its description, usage count, and two example issue titles | learning what a label actually means in this repo — most of the contextual logic lives here |
| `github_find_component_owners(paths_or_keywords[])` | components/labels/maintainers associated with those paths or terms, from recent commits and past assignments | mapping a stack trace or file path to a component and an owner |

### Redaction rule

For the target task's issue — the one whose number equals
`current_case["input"]["issue_number"]` — every tool hides the answer:
`github_get_issue_context` strips that issue's labels, assignee, milestone, state,
`closed_at`, comments and linked PRs/commits; `github_search_similar_issues` never
returns the target issue itself; `github_get_label_taxonomy`'s example titles are
never drawn from it; `github_find_component_owners` never uses its assignment as
evidence. Every *other* issue is visible in full. So the only way to answer is to
infer the maintainers' conventions from the rest of the repo, which is exactly the
"learn complex contextual logic by analyzing data from third-party tools" behaviour
being tested.

Contextual logic worth learning (and worth watching appear in `memory/rules.jsonl`):
what each label actually means in this repo, file path → component mapping,
Windows/ConPTY reports and where they land, which labels co-occur, who owns what,
and when the maintainers bother to set a priority at all (they set one on roughly
a third of issues).

## Negative tasks

13 tasks carry a `negative:*` tag — issues where the correct answer is "nothing
extra," to catch an agent that invents an answer because the output schema has
a slot for one:

- **`negative:no_priority`** (8 tasks) — issues whose language reads as urgent
  (words like "crash", "broken", "critical", "outage") but where the maintainers
  set **no** priority at all. Correct answer: `"none"`. Selected as the 8 oldest
  of the ~24 tasks in the corpus that qualify, so the tag marks a deliberate
  highlight set rather than just relabelling the existing `no-priority` tag
  under a new name.
- **`negative:not_duplicate`** (5 tasks: `gh-4420`, `gh-4452`, `gh-4520`,
  `gh-4639`, `gh-4908`) — issues whose own body raises and resolves the
  duplicate/related-issue question (an explicit "Duplicate search" section, or
  language distinguishing the bug from a similar-sounding prior one, or a
  failure that recurs until a restart) while `duplicate_of` stays `null`.
  Correct answer: `null`. Unlike `no_priority`, this can't be swept up by a
  keyword rule with an acceptable false-positive rate — the same words
  ("duplicate," "again," "related") also appear as ordinary engineering
  vocabulary (a *duplicate CLI invocation*, a bug that happens *again* under
  certain conditions) with no bearing on whether the issue itself is a
  duplicate report. These five were located by reading the corpus and are
  pinned by id in `scripts/build_github_cases.py`.

**`negative:no_extra_labels`** — the addendum's other illustrative example
(issues whose only labels are `comp/*`, so the graded `labels` field is empty)
does not occur anywhere in this repo's 1304 closed issues, checked exhaustively
and without a body-length floor: every `comp/*`-labelled issue here also
carries a type label (`bug` on 47/60 tasks, `enhancement` on 13, `cloud` on 4,
`needs-triage` on 1). There is nothing to tag and nothing to swap in from the
wider corpus — this is a real property of how this repo's maintainers triage,
reported honestly rather than manufactured.

## Splits — temporal, not random

Sorted by `created_at`: **oldest 42 → `train`, newest 18 → `holdout`.**

This is deliberate and it is the point. The improvement loop only ever sees the
older issues; every rule the agent writes into its memory is derived from issues
that predate the holdout. The holdout is then, literally, *"apply that context in
later runs"* — issues filed after everything the agent knows was written, that it
could not have memorized. A random split would let the agent learn from an issue
filed the same week as the one it is graded on; a temporal split cannot.

Holdout is never shown to the improver (PLAN.md §4.3). It is run only for reporting
after a fix is accepted.

## Corpus at a glance

60 tasks · 42 train / 18 holdout · created 2026-08-23 → 2026-09-04 (holdout begins
2026-08-31).

| | |
|---|---|
| components | `comp/daemon` 33 · `comp/desktop` 31 · `comp/cli` 3 · `comp/mobile` 1 |
| priorities | `none` 41 · `P1` 9 · `P2` 9 · `P0` 1 |
| labels | `bug` 47 · `enhancement` 13 · `cloud` 4 · `needs-triage` 1 |

`tags` carries `comp:<name>` per component and `prio:<P0\|P1\|P2\|none>`, plus the
hard-case tags failure analysis groups on: `multi-component` (8), `no-priority` (41),
`assigned` (31), `windows` (8), `short-body` (2, < 300 chars), `long-body`
(30, > 3000 chars), `duplicate`, `negative:no_priority` (8), and
`negative:not_duplicate` (5) — see *Negative tasks* above.

`duplicate` currently matches **no** task: the repo has only 7 `duplicate`-labelled
issues in 1304 closed ones and none fall inside the 60 most recent component-labelled
issues. The tag and the `duplicate_of` field are defined so that added tasks and the
regression-case path get them for free; today every `duplicate_of` is `null` and the
README says so rather than the corpus pretending otherwise.

`comp/docs-site` is absent because the whole repo has exactly one such issue.

## Reproducing the corpus

```bash
python scripts/build_github_cases.py --repo Untrivial-ai/agent-orchestrator
```

Needs `GITHUB_TOKEN` (or an authenticated `gh` CLI) and stdlib only. It selects the
60 most recent closed non-PR issues that carry at least one `comp/*` label and a body
of at least 80 characters, widening backwards if fewer than 4 components are covered,
then writes a raw snapshot of each issue **and its comments** to
`fixtures/github_triage/issues/<number>.json` before deriving `cases.jsonl` from those
snapshots. The snapshots are the reproducibility record: re-running the script with
them present rebuilds `cases.jsonl` byte-for-byte with no network access, so a later
edit or re-close on GitHub can never silently move the ground truth.
