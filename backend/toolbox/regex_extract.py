"""Tool: pull substrings out of text with a regular expression."""

from __future__ import annotations

import re

from ._common import err, get_int, get_str, ok

_FLAG_MAP = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}

TOOL = {
    "name": "regex_extract",
    "description": (
        "Find every match of a Python regular expression in a block of text.\n"
        "\n"
        "Returns JSON {'pattern', 'match_count', 'matches': [...]}. Each match "
        "is the whole match by default; if the pattern has capture groups, each "
        "match is the list of that match's groups (or a single group when you "
        "pass 'group'). Matches are returned in the order they occur.\n"
        "\n"
        "Use this for surgical extraction once you know the shape of what you "
        "are looking for: an id, a currency amount, an href, a date stamp, a "
        "line prefix. It is cheaper and more reliable than eyeballing a long "
        "document.\n"
        "\n"
        "It does NOT replace or rewrite text, does NOT parse nested structures "
        "such as HTML or JSON (use html_to_text or json_validate for those), "
        "and does NOT interpret the matches — '3.5M' comes back as the literal "
        "string '3.5M', so pass it to number_parse if you need a value.\n"
        "\n"
        "Arguments: 'pattern' is Python `re` syntax. 'text' is what to search. "
        "'flags' is a string of any of i (ignore case), m (multiline ^/$), "
        "s (dot matches newline), x (verbose). 'group' selects one capture "
        "group by number or name. 'max_matches' (default 100) caps the result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "text": {"type": "string", "description": "Text to search."},
            "flags": {
                "type": "string",
                "description": "Any combination of the letters i, m, s, x. Default none.",
            },
            "group": {
                "type": ["string", "integer"],
                "description": "Capture group number or name to return instead of all groups.",
            },
            "max_matches": {
                "type": "integer",
                "description": "Maximum number of matches to return. Default 100.",
                "minimum": 1,
            },
        },
        "required": ["pattern", "text"],
        "additionalProperties": False,
    },
}


def _compile(pattern: str, flag_letters: str) -> re.Pattern:
    flags = 0
    for letter in flag_letters:
        if letter not in _FLAG_MAP:
            raise ValueError(f"unknown flag {letter!r}; allowed flags are i, m, s, x")
        flags |= _FLAG_MAP[letter]
    return re.compile(pattern, flags)


def run(input: dict) -> str:
    try:
        pattern = get_str(input, "pattern")
        text = get_str(input, "text")
        flag_letters = get_str(input, "flags", required=False).lower()
        max_matches = get_int(
            input, "max_matches", required=False, default=100, minimum=1
        )
        compiled = _compile(pattern, flag_letters)
    except (TypeError, ValueError) as exc:
        return err(f"regex_extract: {exc}")
    except re.error as exc:
        return err(f"regex_extract: invalid regular expression {pattern!r} ({exc})")

    group = input.get("group", None)
    matches: list = []
    for match in compiled.finditer(text):
        if group is not None:
            try:
                matches.append(match.group(group))
            except (IndexError, re.error):
                return err(f"regex_extract: pattern has no group {group!r}")
        elif compiled.groups:
            matches.append(list(match.groups()))
        else:
            matches.append(match.group(0))
        if len(matches) >= max_matches:
            break

    return ok({"pattern": pattern, "match_count": len(matches), "matches": matches})
