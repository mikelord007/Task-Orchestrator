"""Tool: fetch one issue by number."""

from __future__ import annotations

from .. import github
from .._common import err, get_int

TOOL = {
    "name": "github_get_issue",
    "description": (
        "Fetch a single issue from this repository by its number.\n"
        "\n"
        "Returns JSON with number, title, body (truncated to 4000 characters), "
        "labels (names only), state, state_reason, assignee, assignees, "
        "milestone, author, comment count, created_at, updated_at, closed_at "
        "and html_url.\n"
        "\n"
        "Use it to read the issue you have been asked about, and to inspect a "
        "specific issue another one references (for example a suspected "
        "duplicate) without paging through a list.\n"
        "\n"
        "It does NOT return the comment thread -- the 'comments' field is only a "
        "count; call github_list_issue_comments for the bodies. It does NOT "
        "accept pull request numbers (a PR number returns an error saying so), "
        "does NOT search by title, and does NOT modify anything.\n"
        "\n"
        "If the number you request is the issue under evaluation, the response "
        "comes back with 'redacted': true and without labels, assignees, "
        "milestone, state, closed_at and state_reason. That is deliberate: "
        "those fields are the answer you are being asked to produce. Read the "
        "title and body, then learn the conventions from other issues.\n"
        "\n"
        "Arguments: 'number' is the issue number as shown in the URL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "Issue number.", "minimum": 1},
        },
        "required": ["number"],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        number = get_int(input, "number", minimum=1)
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.get_issue(number)
