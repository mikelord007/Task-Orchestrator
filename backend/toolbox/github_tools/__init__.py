"""The four agent-facing GitHub tools (PLAN_ADDENDUM.md section F).

Per Anthropic's tools-for-agents guidance, these are consolidated and
task-shaped rather than one wrapper per REST endpoint: ``issue_context``,
``similar_issues``, ``label_taxonomy``, ``component_owners``. Each composes
one or more of the cache-through primitives in ``toolbox.github`` (list_issues,
get_issue, list_issue_comments, list_labels, search_issues, get_file,
list_recent_commits, get_issue_timeline, get_commit, get_pull_files), which
are not themselves exposed to an agent.

Every tool in this package is read-only. Nothing here creates, edits, closes,
labels, assigns or comments on anything; the agent proposes triage, a human
applies it.
"""
