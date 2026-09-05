"""Tool: list every label defined in the repository."""

from __future__ import annotations

from .. import github

TOOL = {
    "name": "github_list_labels",
    "description": (
        "List every label defined in this repository, with its description.\n"
        "\n"
        "Returns JSON {'repo', 'count', 'labels': [{'name', 'description', "
        "'color'}]}, up to 100 labels.\n"
        "\n"
        "Call this once, early, before you propose any labels. It is the only "
        "authoritative list of label names that exist here -- a label you invent "
        "is always wrong, and label names in this repo may be spelled in ways "
        "you would not guess (prefixes, colons, hyphens, casing). The "
        "'description' field is the maintainers' own statement of what each "
        "label means; treat it as the definition.\n"
        "\n"
        "It does NOT say how often a label is used, which labels are applied "
        "together, or which are effectively retired -- for that, list or search "
        "closed issues filtered by the label. It does NOT create labels and "
        "does NOT apply them.\n"
        "\n"
        "Takes no arguments."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}


def run(input: dict) -> str:
    return github.list_labels()
