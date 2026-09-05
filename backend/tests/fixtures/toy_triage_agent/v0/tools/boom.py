"""Toy tool that always raises, to prove an exception never kills a case."""

TOOL = {
    "name": "always_fails",
    "description": "Always raises. Exists only to exercise the tool-error path.",
    "input_schema": {"type": "object", "properties": {}},
}


def run(input: dict) -> str:
    raise ValueError("tool exploded")
