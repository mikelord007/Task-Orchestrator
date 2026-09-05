"""Tool: list issues in the configured repository."""

from __future__ import annotations

from .. import github
from .._common import err, get_int, get_str

TOOL = {
    "name": "github_list_issues",
    "description": (
        "List issues in this repository, newest first.\n"
        "\n"
        "Returns JSON {'repo', 'state', 'page', 'count', 'issues': [...]}. Each "
        "issue carries number, title, body (truncated to 4000 characters), "
        "labels (names only), state, state_reason, assignee, assignees, "
        "milestone, author, comment count, created_at, updated_at, closed_at "
        "and html_url.\n"
        "\n"
        "This is the main way to learn how this repository is actually "
        "maintained: page through closed issues to see which labels are used "
        "together, which words in a title lead to which label, and who gets "
        "assigned what. Filter with 'labels' to see every example of a label "
        "you are unsure about. Use state='closed' for settled, fully triaged "
        "examples; open issues are often still untriaged and are weaker "
        "evidence.\n"
        "\n"
        "It does NOT include pull requests -- they are filtered out, so counts "
        "may be smaller than the page size. It does NOT return comment bodies "
        "(use github_list_issue_comments), does NOT search full text (use "
        "github_search_issues), does NOT sort by anything other than GitHub's "
        "default recently-updated order, and does NOT modify anything.\n"
        "\n"
        "For the one issue you are being asked to triage, the maintainer-applied "
        "fields are withheld and the issue is marked 'redacted': that is "
        "expected, not an error. Do not try to route around it.\n"
        "\n"
        "Arguments: 'state' is open, closed or all (default open). 'labels' is "
        "a comma-separated list and matches issues carrying ALL of them. "
        "'since' is an ISO-8601 timestamp and returns only issues updated after "
        "it. 'page' starts at 1. 'per_page' defaults to 30 and is capped at 100."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "Which issues to return. Default 'open'.",
            },
            "labels": {
                "type": "string",
                "description": "Comma-separated label names; matches issues having all of them.",
            },
            "since": {
                "type": "string",
                "description": "ISO-8601 timestamp; only issues updated after it.",
            },
            "page": {"type": "integer", "minimum": 1, "description": "1-based page. Default 1."},
            "per_page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Issues per page. Default 30, maximum 100.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        state = get_str(input, "state", required=False, default="open") or "open"
        if state not in {"open", "closed", "all"}:
            raise ValueError(f"'state' must be open, closed or all, got {state!r}")
        labels = get_str(input, "labels", required=False) or None
        since = get_str(input, "since", required=False) or None
        page = get_int(input, "page", required=False, default=1, minimum=1)
        per_page = get_int(
            input, "per_page", required=False, default=github.DEFAULT_PER_PAGE, minimum=1
        )
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.list_issues(
        state=state, labels=labels, since=since, page=page, per_page=per_page
    )
