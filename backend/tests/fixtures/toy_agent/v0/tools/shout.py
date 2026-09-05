"""Toy tool used by the Phase 0 contract tests."""

TOOL = {
    "name": "shout",
    "description": (
        "Returns the given text uppercased with a trailing exclamation mark. "
        "Use it whenever the answer must be emphatic. It does NOT translate, "
        "summarize or fetch anything -- it only transforms the string you pass."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The text to shout."}},
        "required": ["text"],
    },
}


def run(input: dict) -> str:  # noqa: A002 - the contract fixes this parameter name
    return f"{str(input.get('text', '')).upper()}!"
