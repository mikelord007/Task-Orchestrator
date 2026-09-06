# `backend/toolbox/`

Reusable tools for generated agents: five offline helpers
(`html_to_text`, `regex_extract`, `date_parse`, `json_validate`, `number_parse`)
and the four consolidated GitHub tools in `github_tools/`. See
`registry.py` for what is registered and how a tool gets materialised into an
agent package.

## The redaction invariant

`github.py` is a cache-through client for one repo, sitting underneath the
four agent-facing tools. Every response it returns is checked against
`contracts.context.current_case`: if the case names an issue (via
`input.issue_number`, or `input.number` as a fallback matching
`contracts/context.py`'s own docstring example), that issue's ground truth is
stripped before the tool's return value ever reaches the model.

**What is redacted, and why each one matters:**

- `labels`, `assignees`, `assignee`, `milestone`, `state`, `state_reason`,
  `closed_at` -- these *are* the answer the agent is being asked to produce
  (or trivially derive it from).
- `updated_at` -- on a closed issue this is usually the same timestamp as
  `closed_at` (whichever event happened last), so it leaks the same fact by a
  different name.
- `comments` (the *count*) -- whether an issue was discussed at all is weak
  but real signal correlated with triage outcomes (see `state_reason`,
  duplicates), so the count goes too. The comment *bodies* are handled
  separately, below.
- The full comment thread and any linked pull requests / commits -- these are
  where maintainers say out loud what they decided and why (`"dupe of #123"`,
  `"moving this to the daemon component"`); leaving them visible would hand
  the agent the reasoning behind the answer, not just the answer.

**Where it is enforced, and why each primitive not listed here is unreachable
for the target issue:**

- `get_issue`, `list_issues`, `search_issues` -- `_redact()` in `github.py`
  strips the fields above from the matching issue object wherever it appears
  (a single issue or inside an `issues` list), and marks it
  `"redacted": True`.
- `list_issue_comments`, `get_issue_timeline` -- return an empty result with
  an explanatory note for the target issue's number, rather than a partially
  redacted comment/reference list. There is no per-comment or per-reference
  redaction because the maintainers' own words are the leak, not a field on
  them.
- `get_commit`, `get_pull_files` -- addressed by sha / PR number, not issue
  number. They are unreachable for the target's own linked items because
  `get_issue_timeline` (the only path that discovers those shas/numbers)
  already returns nothing for the target -- there is nothing to look up.
- `get_file`, `list_labels`, `list_recent_commits` -- carry no per-issue
  ground truth at all (a file's contents, the repo's label list, and commit
  history are not issue-specific), so they need no redaction.

**Redaction happens on read, not on write.** The cache always stores the full,
unredacted response (`write_cache` never sees `current_case`); `_redact()`
runs every time a cached or freshly fetched response is about to be returned.
One cache therefore serves both an eval run (redacted) and ad hoc exploration
outside an eval (unredacted) correctly.

**The four agent-facing tools inherit this by composition, plus their own
rule:**

- `github_get_issue_context` -- surfaces exactly what the underlying
  primitives already redacted (nothing extra to do).
- `github_search_similar_issues` -- additionally *excludes* the target issue
  from its results entirely (not just redacts it), since "is this a
  duplicate of the target" is exactly the question a search-based redaction
  couldn't hide.
- `github_get_label_taxonomy` -- excludes the target issue from the two
  example titles it shows per label.
- `github_find_component_owners` -- excludes the target issue from the
  evidence (labels/assignee) it aggregates per search term.

Tests: `backend/tests/toolbox/test_github_primitives.py` (primitive-level cache,
redaction, retries) and `test_github_composite_tools.py` (composite-level
redaction and composition), both fully offline against a recorded cache
fixture.
