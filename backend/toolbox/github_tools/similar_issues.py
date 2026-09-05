"""Tool: search for duplicate or precedent issues."""

from __future__ import annotations

from .. import github
from .._common import err, get_int, get_str, ok

DEFAULT_LIMIT = 10
MAX_LIMIT = 30
SUMMARY_LIMIT = 300

TOOL = {
    "name": "github_search_similar_issues",
    "description": (
        "Search this repository's issues for likely duplicates or precedent, "
        "ranked by relevance.\n"
        "\n"
        "Returns JSON {'query', 'state', 'total_count', 'count', 'candidates': "
        "[{'number', 'title', 'labels', 'state', 'summary'}]}, where 'summary' "
        "is the first two lines of the issue body. 'total_count' is how many "
        "issues matched in total, which can exceed 'count' when there were "
        "more matches than 'limit' allowed.\n"
        "\n"
        "Use this to find duplicates and precedent before you commit to a "
        "component, label or duplicate-of decision: search the distinctive "
        "symptom in the issue you are triaging (an error message, a platform "
        "name, a feature) and read how the closest matches were labelled and "
        "whether they were closed as duplicates of something else.\n"
        "\n"
        "It does NOT do semantic or fuzzy matching -- it is keyword search, so "
        "a query that returns nothing usually means your wording differs from "
        "the maintainers', not that no precedent exists; retry with fewer or "
        "different words rather than giving up. It does NOT return comment "
        "bodies (call github_get_issue_context on a candidate number for "
        "that), and it never returns the issue currently under evaluation as "
        "a candidate for itself. If 'total_count' exceeds 'count', narrow the "
        "query instead of raising 'limit' past 30.\n"
        "\n"
        "Arguments: 'query' is the search text; GitHub qualifiers also work "
        "(e.g. 'label:bug', 'author:someone'). 'state' filters to open, closed "
        "or all (default all). 'limit' caps the results, default 10, maximum "
        "30. Example call: github_search_similar_issues(query='resize crash', "
        "state='closed')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms and optional GitHub qualifiers.",
            },
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "Which issues to search. Default 'all'.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_LIMIT,
                "description": "Maximum candidates to return. Default 10, maximum 30.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def _two_line_summary(body: str | None) -> str:
    if not body:
        return ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return " ".join(lines[:2])[:SUMMARY_LIMIT]


def run(input: dict) -> str:
    try:
        query = get_str(input, "query").strip()
        if not query:
            raise ValueError("'query' must not be empty")
        state = get_str(input, "state", required=False, default="all") or "all"
        if state not in {"open", "closed", "all"}:
            raise ValueError(f"'state' must be open, closed or all, got {state!r}")
        limit = get_int(
            input, "limit", required=False, default=DEFAULT_LIMIT, minimum=1
        )
        limit = min(limit, MAX_LIMIT)
    except (TypeError, ValueError) as exc:
        return err(
            f"{TOOL['name']}: {exc}. Example call: "
            "github_search_similar_issues(query='resize crash', state='closed')"
        )

    full_query = query if state == "all" else f"{query} state:{state}"
    payload, error = github.decode(github.search_issues(full_query, per_page=limit))
    if payload is None:
        return err(f"{TOOL['name']}: search failed ({error})")

    target = github.evaluated_issue_number()
    candidates = []
    for issue in payload.get("issues") or []:
        if target is not None and issue.get("number") == target:
            continue
        candidates.append(
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "labels": issue.get("labels"),
                "state": issue.get("state"),
                "summary": _two_line_summary(issue.get("body")),
            }
        )

    result: dict = {
        "query": query,
        "state": state,
        "total_count": payload.get("total_count"),
        "count": len(candidates),
        "candidates": candidates,
    }
    total = payload.get("total_count") or 0
    if total > len(candidates):
        result["note"] = (
            f"{total - len(candidates)} more issues matched but were not returned; "
            "narrow the query rather than raising 'limit' past 30."
        )
    return ok(result)
