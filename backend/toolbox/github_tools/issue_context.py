"""Tool: full context on one issue, in a single call."""

from __future__ import annotations

from .. import github
from .._common import err, get_int, get_str, ok, truncate

MAX_COMMENTS_CONCISE = 5
MAX_COMMENTS_DETAILED = 20
MAX_LINKED_ITEMS = 10
CONCISE_COMMENT_BODY_LIMIT = 400

TOOL = {
    "name": "github_get_issue_context",
    "description": (
        "Get everything there is to know about one issue in a single call: "
        "its title and body, who filed it, its comment thread, and any pull "
        "requests or commits that reference or closed it (with the files "
        "those touched).\n"
        "\n"
        "Returns JSON {'issue': {...}, 'comments': [...], "
        "'comments_truncated_count', 'linked': [...], 'response_format'}. "
        "'issue' has number, title, body, author, labels, state, assignee, "
        "milestone, created_at, closed_at, html_url (fields are omitted where "
        "redacted -- see below). 'comments' is author/created_at/body, capped "
        "at 5 in 'concise' mode and 20 in 'detailed'. 'linked' lists pull "
        "requests and commits that reference this issue; in 'detailed' mode "
        "each carries its number/sha and the files it touched.\n"
        "\n"
        "Use this as your first call on any issue you have been asked to "
        "triage, or on a candidate duplicate you found with "
        "github_search_similar_issues. It replaces separately fetching the "
        "issue, its comments, and its cross-references.\n"
        "\n"
        "It does NOT return other issues (use github_search_similar_issues), "
        "does NOT return the label taxonomy (use github_get_label_taxonomy), "
        "and does NOT modify anything. In 'concise' mode (the default) "
        "comment bodies are shortened and linked items show titles only, with "
        "no ids -- switch to 'detailed' once you know you need a specific "
        "commit sha or PR number for a follow-up call. When the comment "
        "thread is longer than the cap, the response includes a note saying "
        "how many were left out and to re-call with response_format='detailed' "
        "for more.\n"
        "\n"
        "For the issue currently under evaluation, the maintainer-applied "
        "fields (labels, assignees, milestone, state, closed_at) are withheld "
        "and 'comments' and 'linked' come back empty with a note explaining "
        "why -- that data is the answer you are being asked to produce; infer "
        "it from other issues instead.\n"
        "\n"
        "Arguments: 'issue_number' is required, e.g. 202 for issue #202. "
        "'response_format' is 'concise' (default) or 'detailed'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "issue_number": {
                "type": "integer",
                "minimum": 1,
                "description": "The issue number, e.g. 202 for issue #202.",
            },
            "response_format": {
                "type": "string",
                "enum": ["concise", "detailed"],
                "description": (
                    "'concise' (default) shortens comments and hides ids; "
                    "'detailed' exposes ids and shows more."
                ),
            },
        },
        "required": ["issue_number"],
        "additionalProperties": False,
    },
}


def _example_call(number: int) -> str:
    return f"Example call: github_get_issue_context(issue_number={number})"


def _summarize_reference(reference: dict, detailed: bool) -> dict:
    summary = {
        "type": "pull_request" if reference.get("is_pull_request") else "issue",
        "title": reference.get("title"),
    }
    if detailed:
        summary["number"] = reference.get("number")
        summary["state"] = reference.get("state")
    return summary


def _summarize_commit(commit: dict, detailed: bool) -> dict:
    summary = {"type": "commit", "message": commit.get("message")}
    if detailed:
        summary["sha"] = commit.get("sha")
        summary["files"] = commit.get("files")
    return summary


def run(input: dict) -> str:
    try:
        number = get_int(input, "issue_number", minimum=1)
        response_format = (
            get_str(input, "response_format", required=False, default="concise") or "concise"
        )
        if response_format not in {"concise", "detailed"}:
            raise ValueError(
                f"'response_format' must be 'concise' or 'detailed', got {response_format!r}"
            )
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}. {_example_call(input.get('issue_number') or 101)}")

    detailed = response_format == "detailed"

    issue, issue_error = github.decode(github.get_issue(number))
    if issue is None:
        return err(
            f"{TOOL['name']}: could not load issue #{number} ({issue_error}). "
            f"{_example_call(number)}"
        )

    comment_cap = MAX_COMMENTS_DETAILED if detailed else MAX_COMMENTS_CONCISE
    comments_payload, comments_error = github.decode(
        github.list_issue_comments(number, per_page=github.DEFAULT_PER_PAGE)
    )
    comments: list[dict] = []
    comments_note: str | None = None
    truncated_count = 0
    if comments_payload is not None:
        comments_note = comments_payload.get("note")
        all_comments = comments_payload.get("comments") or []
        comments = all_comments[:comment_cap]
        truncated_count = max(0, len(all_comments) - len(comments))
        if not detailed:
            comments = [
                {
                    **comment,
                    "body": truncate(comment.get("body"), CONCISE_COMMENT_BODY_LIMIT),
                }
                for comment in comments
            ]
    elif comments_error:
        comments_note = f"comments unavailable ({comments_error})"

    timeline_payload, timeline_error = github.decode(github.get_issue_timeline(number))
    linked: list[dict] = []
    linked_note: str | None = None
    if timeline_payload is not None:
        if timeline_payload.get("note"):
            linked_note = timeline_payload["note"]
        else:
            references = (timeline_payload.get("references") or [])[:MAX_LINKED_ITEMS]
            linked = [_summarize_reference(reference, detailed) for reference in references]
            for sha in (timeline_payload.get("commit_shas") or [])[:MAX_LINKED_ITEMS]:
                commit_payload, _ = github.decode(github.get_commit(sha))
                if commit_payload is not None:
                    linked.append(_summarize_commit(commit_payload, detailed))
    elif timeline_error:
        linked_note = f"linked items unavailable ({timeline_error})"

    result: dict = {
        "issue": issue,
        "comments": comments,
        "comments_truncated_count": truncated_count,
        "linked": linked,
        "response_format": response_format,
    }
    if truncated_count:
        result["comments_note"] = (
            f"{truncated_count} more comments not shown; call again with "
            "response_format='detailed' to see more of the thread."
        )
    elif comments_note:
        result["comments_note"] = comments_note
    if linked_note:
        result["linked_note"] = linked_note
    return ok(result)
