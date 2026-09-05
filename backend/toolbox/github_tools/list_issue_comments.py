"""Tool: read the comment thread on one issue."""

from __future__ import annotations

from .. import github
from .._common import err, get_int

TOOL = {
    "name": "github_list_issue_comments",
    "description": (
        "Read the comment thread on one issue.\n"
        "\n"
        "Returns JSON {'issue_number', 'count', 'comments': [{'author', "
        "'created_at', 'body'}]} in chronological order, each body truncated to "
        "2000 characters.\n"
        "\n"
        "Comments are where maintainers say out loud what they are doing and "
        "why: 'this is a dupe of #412', 'moving this to the runtime component', "
        "'this is really a docs problem'. On a closed, well-triaged issue the "
        "thread is the best available explanation of why the labels ended up "
        "the way they did. Use it on comparable past issues to learn the "
        "conventions.\n"
        "\n"
        "It does NOT return review comments on pull requests, does NOT include "
        "the issue body itself (call github_get_issue for that), does NOT show "
        "reactions, edits or hidden comments, and does NOT post anything.\n"
        "\n"
        "For the issue under evaluation this returns an empty list with the "
        "note 'comments hidden for the issue under evaluation'. That is not a "
        "failure and not a sign of an empty thread -- maintainer comments on "
        "that issue would leak the answer. Base your triage on the issue text "
        "plus what you learned from other issues.\n"
        "\n"
        "Arguments: 'number' is the issue number. 'per_page' defaults to 30 and "
        "is capped at 100."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "Issue number.", "minimum": 1},
            "per_page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Comments to return. Default 30, maximum 100.",
            },
        },
        "required": ["number"],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        number = get_int(input, "number", minimum=1)
        per_page = get_int(
            input, "per_page", required=False, default=github.DEFAULT_PER_PAGE, minimum=1
        )
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.list_issue_comments(number, per_page=per_page)
