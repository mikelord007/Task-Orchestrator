"""Tool: full-text search over the repository's issues."""

from __future__ import annotations

from .. import github
from .._common import err, get_int, get_str

TOOL = {
    "name": "github_search_issues",
    "description": (
        "Full-text search over this repository's issues.\n"
        "\n"
        "Returns JSON {'repo', 'query', 'total_count', 'count', 'issues': "
        "[...]} with the same trimmed issue shape as github_list_issues. "
        "'total_count' is how many issues matched in total; 'count' is how many "
        "are on this page.\n"
        "\n"
        "This is the fastest way to find precedent. Search the distinctive "
        "words from the issue you are triaging -- an error message, a component "
        "name, a platform -- and read how the matching past issues were "
        "labelled. It is also how you find duplicates: search the specific "
        "symptom, not a generic paraphrase.\n"
        "\n"
        "The scope 'repo:<this repo> is:issue' is added for you, so do not "
        "include it. GitHub search qualifiers do work in the rest of the query: "
        "'state:closed', 'label:bug', 'in:title', 'author:someone', "
        "'created:>2024-01-01'. Quote multi-word phrases.\n"
        "\n"
        "It does NOT search code, commits, comments-only, or other "
        "repositories. It does NOT do semantic or fuzzy matching -- it is "
        "keyword search, so a query that returns nothing usually means your "
        "wording differs from the maintainers', not that no precedent exists; "
        "retry with fewer or different words. Results are ranked by relevance, "
        "not by date.\n"
        "\n"
        "Arguments: 'q' is the query. 'page' starts at 1. 'per_page' defaults "
        "to 30 and is capped at 100."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "q": {
                "type": "string",
                "description": "Search terms and optional GitHub qualifiers. No repo: scope needed.",
            },
            "page": {"type": "integer", "minimum": 1, "description": "1-based page. Default 1."},
            "per_page": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Results per page. Default 30, maximum 100.",
            },
        },
        "required": ["q"],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    try:
        query = get_str(input, "q").strip()
        if not query:
            raise ValueError("'q' must not be empty")
        page = get_int(input, "page", required=False, default=1, minimum=1)
        per_page = get_int(
            input, "per_page", required=False, default=github.DEFAULT_PER_PAGE, minimum=1
        )
    except (TypeError, ValueError) as exc:
        return err(f"{TOOL['name']}: {exc}")
    return github.search_issues(query, page=page, per_page=per_page)
