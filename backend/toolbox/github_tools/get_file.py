"""Tool: read a file from the repository's default branch."""

from __future__ import annotations

from .. import github
from .._common import err, get_str

TOOL = {
    "name": "github_get_file",
    "description": (
        "Read one file (or list one directory) from this repository.\n"
        "\n"
        "For a file, returns JSON {'repo', 'path', 'type': 'file', 'size', "
        "'content'} with the text decoded and truncated to 20000 characters. "
        "For a directory path, returns {'type': 'dir', 'entries': [{'name', "
        "'type'}]} so you can explore the tree.\n"
        "\n"
        "Use it to ground component and ownership decisions in what the "
        "repository actually contains: read CONTRIBUTING.md or a "
        ".github/ISSUE_TEMPLATE file for the maintainers' stated triage rules, "
        "read CODEOWNERS to see who owns which path, and list the top-level "
        "source directories to learn the real component names instead of "
        "guessing them from the issue text.\n"
        "\n"
        "It does NOT search across files (there is no code search here; use "
        "github_search_issues for issue text), does NOT return binary files "
        "(they come back with an explanatory error), does NOT return file "
        "history (use github_list_recent_commits), and does NOT write anything.\n"
        "\n"
        "Arguments: 'path' is repo-relative with no leading slash, e.g. "
        "'CONTRIBUTING.md' or 'src/runtime'. 'ref' is an optional branch, tag "
        "or commit sha; it defaults to the repository's default branch."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repo-relative file or directory path, no leading slash.",
            },
            "ref": {
                "type": "string",
                "description": "Branch, tag or commit sha. Defaults to the default branch.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        path = get_str(input, "path").strip().lstrip("/")
        if not path:
            raise ValueError("'path' must not be empty")
        ref = get_str(input, "ref", required=False) or None
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.get_file(path, ref=ref)
