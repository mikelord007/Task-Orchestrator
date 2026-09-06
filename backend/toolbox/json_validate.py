"""Tool: check that a string is JSON of the shape the caller expects."""

from __future__ import annotations

import json
import re

from ._common import err, ok

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)

_TYPE_NAMES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}

TOOL = {
    "name": "json_validate",
    "description": (
        "Parse a string as JSON and report exactly what is wrong if it is not.\n"
        "\n"
        "Returns JSON {'valid': bool, 'errors': [str], 'top_level_type', "
        "'keys': [...], 'parsed': ...} on success, or an error string naming "
        "the syntax problem and the line and column where it was found. A "
        "single ```json fenced block is unwrapped before parsing.\n"
        "\n"
        "Use this as the last step before you emit a structured answer: run "
        "your candidate JSON through it with 'required_keys' set to the keys "
        "the task asks for, and fix whatever it reports. That is much cheaper "
        "than having the whole answer rejected.\n"
        "\n"
        "It does NOT repair or reformat the JSON for you, does NOT apply a full "
        "JSON Schema (only top-level type and required-key checks), does NOT "
        "check value types inside the object, and does NOT tell you whether the "
        "values are correct — only that the document parses and has the keys.\n"
        "\n"
        "Arguments: 'text' is the candidate JSON. 'required_keys' is a list of "
        "keys that must be present when the top level is an object. "
        "'expect_type' is one of object, array, string, number, boolean, null."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Candidate JSON document."},
            "required_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys that must be present at the top level.",
            },
            "expect_type": {
                "type": "string",
                "enum": sorted(_TYPE_NAMES),
                "description": "Required JSON type of the top-level value.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def run(input: dict) -> str:
    text = input.get("text", None)
    if not isinstance(text, str):
        return err("json_validate: missing required string argument 'text'")

    fence = _FENCE_RE.match(text)
    candidate = fence.group(1) if fence else text

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return err(
            f"json_validate: not valid JSON — {exc.msg} at line {exc.lineno} "
            f"column {exc.colno} (character {exc.pos})."
        )

    errors: list[str] = []

    expect_type = input.get("expect_type", None)
    if expect_type is not None:
        if expect_type not in _TYPE_NAMES:
            return err(
                f"json_validate: unknown expect_type {expect_type!r}; "
                f"allowed values are {', '.join(sorted(_TYPE_NAMES))}"
            )
        actual = _type_name(parsed)
        if actual != expect_type:
            errors.append(f"top level is {actual}, expected {expect_type}")

    required_keys = input.get("required_keys", None) or []
    if required_keys:
        if not isinstance(required_keys, list):
            return err("json_validate: 'required_keys' must be a list of strings")
        if not isinstance(parsed, dict):
            errors.append(
                f"required_keys was given but the top level is {_type_name(parsed)}, not an object"
            )
        else:
            missing = [key for key in required_keys if key not in parsed]
            if missing:
                errors.append(f"missing required keys: {', '.join(missing)}")

    return ok(
        {
            "valid": not errors,
            "errors": errors,
            "top_level_type": _type_name(parsed),
            "keys": sorted(parsed) if isinstance(parsed, dict) else None,
            "parsed": parsed,
        }
    )
