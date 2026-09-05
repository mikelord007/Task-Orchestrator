"""Tool: who owns a path or keyword, from commit history and past issues."""

from __future__ import annotations

from .. import github
from .._common import err, ok

MAX_TERMS = 5
MAX_ISSUES_PER_TERM = 10
MAX_COMMITS_PER_TERM = 10

TOOL = {
    "name": "github_find_component_owners",
    "description": (
        "For one or more file paths or keywords, find who has recently "
        "worked on them and how past issues mentioning them were labelled "
        "and assigned.\n"
        "\n"
        "Returns JSON {'results': [{'term', 'recent_authors': [...], "
        "'labels_seen': [...], 'assignees_seen': [...], "
        "'evidence_issue_numbers': [...]}]}, one entry per term you passed "
        "in, in the order given. 'recent_authors' comes from commit history "
        "scoped to that path, most recent first and deduplicated; "
        "'labels_seen' and 'assignees_seen' come from past issues whose "
        "title or body mentions the term.\n"
        "\n"
        "Use this to ground a component or assignee suggestion in evidence "
        "instead of guessing from the term's surface meaning: pass file "
        "paths you found in a stack trace or in github_get_issue_context's "
        "linked commits, or keywords from the issue title (a subsystem name, "
        "a platform).\n"
        "\n"
        "It does NOT guarantee an active owner -- a single old commit or one "
        "loosely related issue is weak evidence; prefer a term with several "
        "consistent hits. It does NOT look inside file contents (use "
        "github_get_file for that) and never uses the issue currently under "
        "evaluation as evidence for its own assignment.\n"
        "\n"
        "Arguments: 'paths_or_keywords' is a non-empty list of strings, each "
        "either a repo-relative path (e.g. 'src/terminal') or a plain "
        "keyword (e.g. 'windows'). At most 5 terms are investigated per "
        "call. Example call: github_find_component_owners("
        "paths_or_keywords=['src/terminal', 'windows'])."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paths_or_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "File paths or keywords to investigate.",
            },
        },
        "required": ["paths_or_keywords"],
        "additionalProperties": False,
    },
}


def _dedupe_keep_order(values: list) -> list:
    seen: set = set()
    ordered: list = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def run(input: dict) -> str:
    terms = input.get("paths_or_keywords")
    if (
        not isinstance(terms, list)
        or not terms
        or not all(isinstance(term, str) and term.strip() for term in terms)
    ):
        return err(
            f"{TOOL['name']}: 'paths_or_keywords' must be a non-empty list of non-empty "
            "strings. Example call: github_find_component_owners("
            "paths_or_keywords=['src/terminal', 'windows'])"
        )

    all_terms = [term.strip() for term in terms]
    terms_to_run = all_terms[:MAX_TERMS]
    target = github.evaluated_issue_number()

    results = []
    for term in terms_to_run:
        commits_payload, commits_error = github.decode(
            github.list_recent_commits(path=term, per_page=MAX_COMMITS_PER_TERM)
        )
        recent_authors: list[str] = []
        if commits_payload is not None:
            recent_authors = _dedupe_keep_order(
                commit.get("author")
                for commit in (commits_payload.get("commits") or [])
            )

        search_payload, search_error = github.decode(
            github.search_issues(term, per_page=MAX_ISSUES_PER_TERM)
        )
        labels_seen: list[str] = []
        assignees_seen: list[str] = []
        evidence_numbers: list[int] = []
        if search_payload is not None:
            for issue in search_payload.get("issues") or []:
                if target is not None and issue.get("number") == target:
                    continue
                labels_seen.extend(issue.get("labels") or [])
                if issue.get("assignee"):
                    assignees_seen.append(issue["assignee"])
                if issue.get("number") is not None:
                    evidence_numbers.append(issue["number"])

        entry = {
            "term": term,
            "recent_authors": recent_authors,
            "labels_seen": _dedupe_keep_order(labels_seen),
            "assignees_seen": _dedupe_keep_order(assignees_seen),
            "evidence_issue_numbers": evidence_numbers,
        }
        if commits_error and not recent_authors:
            entry["commits_note"] = f"recent commits unavailable ({commits_error})"
        if search_error and search_payload is None:
            entry["issues_note"] = f"issue search unavailable ({search_error})"
        results.append(entry)

    payload: dict = {"results": results}
    if len(all_terms) > MAX_TERMS:
        payload["note"] = (
            f"only the first {MAX_TERMS} of {len(all_terms)} terms were investigated; "
            "call again with the rest."
        )
    return ok(payload)
