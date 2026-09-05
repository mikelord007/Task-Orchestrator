"""Tool: list recent commits, optionally scoped to one path."""

from __future__ import annotations

from .. import github
from .._common import err, get_int, get_str

TOOL = {
    "name": "github_list_recent_commits",
    "description": (
        "List recent commits on the default branch, newest first.\n"
        "\n"
        "Returns JSON {'repo', 'path', 'count', 'commits': [{'sha' (short), "
        "'message' (first line only, 200 characters), 'author', 'date', "
        "'html_url'}]}.\n"
        "\n"
        "Use it to see what is actively being worked on and by whom. Scoping to "
        "a 'path' answers 'who touches this area?', which is the evidence for "
        "an assignee suggestion and for mapping a file path to a component. "
        "Commit dates also tell you whether an area is live or dormant, which "
        "affects priority.\n"
        "\n"
        "It does NOT return diffs, changed-file lists or commit bodies -- only "
        "the subject line. It does NOT cover other branches or pull requests "
        "that were never merged, does NOT search commit text, and does NOT "
        "prove ownership on its own: a single drive-by commit is weak evidence "
        "compared with CODEOWNERS or a repeated assignee pattern in past "
        "issues.\n"
        "\n"
        "Arguments: 'path' is an optional repo-relative file or directory that "
        "limits the history. 'per_page' defaults to 30 and is capped at 100."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional repo-relative path to limit the history to.",
            },
            "per_page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Commits to return. Default 30, maximum 100.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        path = get_str(input, "path", required=False).strip().lstrip("/") or None
        per_page = get_int(
            input, "per_page", required=False, default=github.DEFAULT_PER_PAGE, minimum=1
        )
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.list_recent_commits(path=path, per_page=per_page)
