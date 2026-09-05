"""Tool: read numbers, currency amounts and magnitude suffixes out of text."""

from __future__ import annotations

import re

from ._common import err, get_str, ok

_MULTIPLIERS = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
    "lakh": 100_000,
    "crore": 10_000_000,
}

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}

_MULT_ALT = "|".join(sorted(_MULTIPLIERS, key=len, reverse=True))
_SYMBOL_ALT = "|".join(
    re.escape(sym) for sym in sorted(_CURRENCY_SYMBOLS, key=len, reverse=True)
)
_CODE_ALT = "USD|EUR|GBP|JPY|INR|CAD|AUD|CHF"

_NUMBER_RE = re.compile(
    rf"(?P<sym>{_SYMBOL_ALT})?\s*"
    rf"(?P<num>[+-]?\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|[+-]?\d*\.\d+|[+-]?\d+)"
    rf"\s*(?P<mult>{_MULT_ALT})?\b"
    rf"(?:\s*(?P<code>{_CODE_ALT}))?"
    rf"(?P<pct>\s*%)?",
    re.IGNORECASE,
)

TOOL = {
    "name": "number_parse",
    "description": (
        "Extract numeric values from text, resolving thousands separators, "
        "magnitude suffixes and currency markers.\n"
        "\n"
        "Returns JSON {'input', 'count', 'numbers': [{'value', 'raw', "
        "'currency', 'is_percent'}]}, in the order the numbers appear. "
        "'$1.2M' becomes 1200000.0 with currency USD; '12,500' becomes 12500.0; "
        "'3.5 billion' becomes 3500000000.0; '15%' becomes 15.0 with "
        "is_percent true; '2 crore' and '5 lakh' are supported.\n"
        "\n"
        "Use it whenever a prize pool, price, count or threshold has to end up "
        "in a structured answer as a number rather than as prose.\n"
        "\n"
        "It does NOT convert between currencies (the code is reported, never "
        "applied), does NOT add the numbers up, does NOT turn a percentage into "
        "a fraction (15% is 15.0, not 0.15), does NOT read numbers spelled out "
        "as words ('two million'), and does NOT parse dates — a year like 2024 "
        "comes back as the number 2024.0, so filter by context or use "
        "date_parse.\n"
        "\n"
        "Arguments: 'text' is the string to scan. 'first_only' (default false) "
        "returns just the first number. 'currency' filters the result to "
        "amounts carrying that ISO code or its symbol."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to scan for numbers."},
            "first_only": {
                "type": "boolean",
                "description": "Return only the first number found. Default false.",
            },
            "currency": {
                "type": "string",
                "description": "Keep only amounts in this ISO currency code, e.g. USD.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def run(input: dict) -> str:
    try:
        text = get_str(input, "text")
        currency_filter = get_str(input, "currency", required=False).upper() or None
    except (TypeError, ValueError) as exc:
        return err(f"number_parse: {exc}")
    first_only = bool(input.get("first_only", False))

    numbers: list[dict] = []
    for match in _NUMBER_RE.finditer(text):
        value = _to_float(match.group("num"))
        if value is None:
            continue
        multiplier = match.group("mult")
        if multiplier:
            value *= _MULTIPLIERS[multiplier.lower()]
        symbol = match.group("sym")
        code = match.group("code")
        currency = None
        if symbol:
            currency = _CURRENCY_SYMBOLS.get(symbol) or _CURRENCY_SYMBOLS.get(
                symbol.upper()
            )
        if code:
            currency = code.upper()
        entry = {
            "value": value,
            "raw": match.group(0).strip(),
            "currency": currency,
            "is_percent": bool(match.group("pct")),
        }
        if currency_filter and currency != currency_filter:
            continue
        numbers.append(entry)
        if first_only:
            break

    return ok({"input": text[:200], "count": len(numbers), "numbers": numbers})
