# `github_triage`

Triage a real GitHub issue the way this repository's maintainers actually triage it.

The corpus is 60 **closed** issues from [`Untrivial-ai/agent-orchestrator`](https://github.com/Untrivial-ai/agent-orchestrator)
— the AO project itself. Ground truth is what the maintainers really applied before
closing: their labels, their component labels, their priority, their assignee.

This is the domain with **third-party tool access**. The agent is not handed the
repo's conventions; it has to discover them by reading *other* issues through the
GitHub tools and generalizing.

## The task

**Input** (`cases.jsonl` → `input`) — never contains any part of the answer:

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

## What "good" means

`score.py` is deterministic, offline, stdlib-only:

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

Backed by `backend/toolbox/github.py` (thin GitHub REST wrappers, cache-through to
`fixtures/github_cache/`, so eval runs are offline and deterministic):

| tool | use |
|---|---|
| `github_list_issues` | browse issues by state/label/date to learn what the labels mean here |
| `github_get_issue` | read another issue in full, including the labels it ended up with |
| `github_list_issue_comments` | see how maintainers discuss, prioritize and close issues |
| `github_list_labels` | the label vocabulary, with descriptions |
| `github_search_issues` | find prior issues with similar symptoms (duplicates, recurring bugs) |
| `github_get_file` | read the repo tree / source to map a stack trace or path to a component |
| `github_list_recent_commits` | see which paths are churning and who touches them |

### Redaction rule

The tools **hide the target issue** — the one whose number equals
`current_case["input"]["issue_number"]`. Its labels, assignee, state and comments
are stripped from every tool response. The agent can still see every *other* issue
in full. So the only way to answer is to infer the maintainers' conventions from
the rest of the repo, which is exactly the "learn complex contextual logic by
analyzing data from third-party tools" behaviour being tested.

Contextual logic worth learning (and worth watching appear in `memory/rules.jsonl`):
what each label actually means in this repo, file path → component mapping,
Windows/ConPTY reports and where they land, which labels co-occur, who owns what,
and when the maintainers bother to set a priority at all (they set one on roughly
a third of issues).

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

60 cases · 42 train / 18 holdout · created 2026-08-23 → 2026-09-04 (holdout begins
2026-08-31).

| | |
|---|---|
| components | `comp/daemon` 33 · `comp/desktop` 31 · `comp/cli` 3 · `comp/mobile` 1 |
| priorities | `none` 41 · `P1` 9 · `P2` 9 · `P0` 1 |
| labels | `bug` 47 · `enhancement` 13 · `cloud` 4 · `needs-triage` 1 |

`tags` carries `comp:<name>` per component and `prio:<P0\|P1\|P2\|none>`, plus the
hard-case tags failure analysis groups on: `multi-component` (8), `no-priority` (41),
`assigned` (31), `windows` (8), `short-body` (2, < 300 chars), `long-body`
(30, > 3000 chars), and `duplicate`.

`duplicate` currently matches **no** case: the repo has only 7 `duplicate`-labelled
issues in 1304 closed ones and none fall inside the 60 most recent component-labelled
issues. The tag and the `duplicate_of` field are defined so that added cases and the
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
