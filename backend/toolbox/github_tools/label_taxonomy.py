"""Tool: every label in the repository, with how it is actually used."""

from __future__ import annotations

from .. import github
from .._common import err, ok

EXAMPLE_COUNT = 2
EXAMPLE_FETCH = 6  # headroom in case the target issue is among the top matches

TOOL = {
    "name": "github_get_label_taxonomy",
    "description": (
        "List every label defined in this repository together with how it is "
        "actually used: its description, how many issues currently carry it, "
        "and two example issue titles.\n"
        "\n"
        "Returns JSON {'count', 'labels': [{'name', 'description', "
        "'usage_count', 'example_titles': [...]}]}.\n"
        "\n"
        "Call this once, early, before proposing any labels for a task -- most "
        "of the contextual, repo-specific knowledge you need lives here. "
        "'description' is the maintainers' own definition of the label; "
        "'usage_count' and the two examples show how it is applied in "
        "practice, which sometimes differs from what the description alone "
        "suggests (a label that reads generically may in practice only ever "
        "be applied to one platform or one kind of report).\n"
        "\n"
        "It does NOT tell you which labels are applied together on the same "
        "issue -- cross-reference with github_search_similar_issues if you "
        "need that -- does NOT create or apply labels, and never uses the "
        "issue currently under evaluation as one of its examples or in its "
        "count.\n"
        "\n"
        "Takes no arguments."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}


def run(input: dict) -> str:
    labels_payload, labels_error = github.decode(github.list_labels())
    if labels_payload is None:
        return err(f"{TOOL['name']}: could not load labels ({labels_error})")

    target = github.evaluated_issue_number()
    result_labels = []
    for label in labels_payload.get("labels") or []:
        name = label.get("name")
        usage_count = 0
        examples: list[str] = []
        if name:
            search_payload, _search_error = github.decode(
                github.search_issues(f'label:"{name}"', per_page=EXAMPLE_FETCH)
            )
            if search_payload is not None:
                usage_count = search_payload.get("total_count") or 0
                for issue in search_payload.get("issues") or []:
                    if target is not None and issue.get("number") == target:
                        continue
                    if issue.get("title"):
                        examples.append(issue["title"])
                    if len(examples) >= EXAMPLE_COUNT:
                        break
        result_labels.append(
            {
                "name": name,
                "description": label.get("description"),
                "usage_count": usage_count,
                "example_titles": examples,
            }
        )

    return ok({"count": len(result_labels), "labels": result_labels})
