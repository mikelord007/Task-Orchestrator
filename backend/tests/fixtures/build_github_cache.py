"""Regenerate the recorded GitHub cache fixture used by the toolbox tests.

The fixture is a small, hand-written stand-in for a real recording against
``acme/widgets``. It is written through ``toolbox.github.write_cache`` so the
files carry exactly the keys the production code computes -- if the cache key
formula ever changes, rerunning this script is what re-syncs the fixture, and
``test_github_cache.py::test_cache_key_is_stable`` is what catches the change.

Run with:  uv run python backend/tests/fixtures/build_github_cache.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CACHE_DIR = HERE / "github_cache"
REPO = "acme/widgets"

#: The issue the evaluator asks about. Its ground truth must never reach the agent.
EVALUATED_ISSUE = 202


def _issue(
    number: int,
    title: str,
    body: str,
    labels: list[str],
    assignee: str | None,
    created_at: str,
    closed_at: str | None,
    comments: int = 0,
    milestone: str | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": labels,
        "state": "closed" if closed_at else "open",
        "state_reason": "completed" if closed_at else None,
        "assignee": assignee,
        "assignees": [assignee] if assignee else [],
        "milestone": milestone,
        "author": "reporter",
        "comments": comments,
        "created_at": created_at,
        "updated_at": closed_at or created_at,
        "closed_at": closed_at,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
    }


ISSUE_101 = _issue(
    101,
    "Terminal output garbled on Windows when resizing",
    "Running the CLI in Windows Terminal, resizing the window corrupts the "
    "output buffer. Repro: start `widget watch`, drag the window edge.",
    ["bug", "platform:windows", "component:terminal"],
    "dana",
    "2024-01-12T09:00:00Z",
    "2024-01-20T17:30:00Z",
    comments=2,
)

ISSUE_140 = _issue(
    140,
    "ConPTY resize corrupts scrollback",
    "Same class of problem as #101 but in the scrollback buffer.",
    ["bug", "platform:windows", "component:terminal"],
    "dana",
    "2024-02-02T11:15:00Z",
    "2024-02-09T08:00:00Z",
    comments=1,
)

ISSUE_155 = _issue(
    155,
    "Document the --json flag",
    "The README does not mention `--json` anywhere.",
    ["docs", "good first issue", "component:docs"],
    "sam",
    "2024-02-14T14:00:00Z",
    "2024-02-15T10:00:00Z",
)

#: The issue under evaluation, recorded in full. Redaction happens on read.
ISSUE_202 = _issue(
    EVALUATED_ISSUE,
    "Window resize breaks the progress bar on Windows Terminal",
    "The progress bar repaints over itself after a resize. Windows 11, "
    "Windows Terminal 1.19.",
    ["bug", "platform:windows", "component:terminal"],
    "dana",
    "2024-03-03T08:20:00Z",
    "2024-03-11T12:00:00Z",
    comments=3,
    milestone="1.5",
)

ENTRIES: list[tuple[str, dict, object]] = [
    (
        "github_list_labels",
        {"repo": REPO},
        {
            "repo": REPO,
            "count": 6,
            "labels": [
                {"name": "bug", "description": "Something is broken", "color": "d73a4a"},
                {"name": "docs", "description": "Documentation only", "color": "0075ca"},
                {
                    "name": "platform:windows",
                    "description": "Only reproduces on Windows",
                    "color": "1d76db",
                },
                {
                    "name": "component:terminal",
                    "description": "Terminal rendering and PTY handling",
                    "color": "5319e7",
                },
                {
                    "name": "component:docs",
                    "description": "README and docs site",
                    "color": "c2e0c6",
                },
                {
                    "name": "good first issue",
                    "description": "Small, well-scoped, newcomer friendly",
                    "color": "7057ff",
                },
            ],
        },
    ),
    (
        "github_list_issues",
        {"repo": REPO, "state": "closed", "page": 1, "per_page": 30},
        {
            "repo": REPO,
            "state": "closed",
            "page": 1,
            "count": 4,
            "issues": [ISSUE_202, ISSUE_155, ISSUE_140, ISSUE_101],
        },
    ),
    ("github_get_issue", {"repo": REPO, "number": 101}, ISSUE_101),
    ("github_get_issue", {"repo": REPO, "number": EVALUATED_ISSUE}, ISSUE_202),
    (
        "github_list_issue_comments",
        {"repo": REPO, "number": 101, "per_page": 30},
        {
            "issue_number": 101,
            "count": 2,
            "comments": [
                {
                    "author": "dana",
                    "created_at": "2024-01-13T10:00:00Z",
                    "body": "This is a ConPTY problem, tagging component:terminal.",
                },
                {
                    "author": "sam",
                    "created_at": "2024-01-20T17:29:00Z",
                    "body": "Fixed in 1.4.2.",
                },
            ],
        },
    ),
    (
        "github_list_issue_comments",
        {"repo": REPO, "number": EVALUATED_ISSUE, "per_page": 30},
        {
            "issue_number": EVALUATED_ISSUE,
            "count": 1,
            "comments": [
                {
                    "author": "dana",
                    "created_at": "2024-03-04T09:00:00Z",
                    "body": "Windows-only again, same component as #101.",
                }
            ],
        },
    ),
    (
        "github_search_issues",
        {"repo": REPO, "q": "resize", "page": 1, "per_page": 30},
        {
            "repo": REPO,
            "query": "resize",
            "total_count": 3,
            "count": 3,
            "issues": [ISSUE_101, ISSUE_140, ISSUE_202],
        },
    ),
    (
        "github_get_file",
        {"repo": REPO, "path": "CONTRIBUTING.md"},
        {
            "repo": REPO,
            "path": "CONTRIBUTING.md",
            "type": "file",
            "size": 118,
            "content": (
                "# Contributing\n\n"
                "Label every bug with a `component:` label and, if it is platform "
                "specific, a `platform:` label.\n"
            ),
        },
    ),
    (
        "github_list_recent_commits",
        {"repo": REPO, "per_page": 30},
        {
            "repo": REPO,
            "path": None,
            "count": 2,
            "commits": [
                {
                    "sha": "aa11bb22cc33",
                    "message": "terminal: guard against zero-width resize",
                    "author": "Dana",
                    "date": "2024-03-01T09:00:00Z",
                    "html_url": f"https://github.com/{REPO}/commit/aa11bb22cc33",
                },
                {
                    "sha": "dd44ee55ff66",
                    "message": "docs: describe --json",
                    "author": "Sam",
                    "date": "2024-02-15T09:00:00Z",
                    "html_url": f"https://github.com/{REPO}/commit/dd44ee55ff66",
                },
            ],
        },
    ),
]


def main() -> None:
    os.environ["GITHUB_CACHE_DIR"] = str(CACHE_DIR)
    from toolbox import github

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for tool_name, args, response in ENTRIES:
        github.write_cache(tool_name, args, response)
        print(f"{tool_name} {args} -> {github.cache_key(tool_name, args)}.json")


if __name__ == "__main__":
    main()
