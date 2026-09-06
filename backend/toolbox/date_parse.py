"""Tool: normalise a human-written date into ISO-8601."""

from __future__ import annotations

import re
from datetime import date

from ._common import err, get_str, ok

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# 2024-03-07, 2024/03/07
_ISO_RE = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
# 7 March 2024, 7th of March, 2024
_DMY_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_ALT})\.?,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)
# March 7, 2024 / March 7th 2024 / Mar 2024
_MDY_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)
# 03/07/2024 or 03-07-24
_NUMERIC_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")
# bare "March 2024"
_MY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.IGNORECASE)

_TIME_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?\s*([A-Z]{2,5}|UTC[+-]\d{1,2}|[+-]\d{2}:?\d{2})?",
    re.IGNORECASE,
)

TOOL = {
    "name": "date_parse",
    "description": (
        "Turn a date written for humans into an ISO-8601 calendar date.\n"
        "\n"
        "Returns JSON {'input', 'date': 'YYYY-MM-DD'|null, 'time': 'HH:MM'|null, "
        "'timezone': str|null, 'matched_text', 'format'} where 'format' names "
        "the pattern that matched (iso, day-month-year, month-day-year, "
        "numeric, month-year). Handles '7 March 2024', 'March 7th, 2024', "
        "'2024-03-07', '03/07/2024', 'Mar 2024' (day defaults to 1), ordinal "
        "suffixes, and an optional trailing clock time with a timezone label.\n"
        "\n"
        "Use it every time a date has to be compared, sorted or emitted in a "
        "structured answer, so that all dates in your output share one format.\n"
        "\n"
        "It does NOT do date arithmetic, does NOT resolve relative phrases such "
        "as 'next Friday' or 'in two weeks', does NOT convert between "
        "timezones (the label is reported verbatim, never applied), and does "
        "NOT guess a missing year — a date with no year returns "
        "'date': null and tells you the year was missing. If the text holds "
        "several dates only the first is parsed; use regex_extract to split "
        "them apart first.\n"
        "\n"
        "Arguments: 'text' is the string to parse. 'dayfirst' (default false) "
        "disambiguates all-numeric dates like 03/07/2024: false reads it as "
        "March 7 (US order), true as 3 July (EU order)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text containing a date."},
            "dayfirst": {
                "type": "boolean",
                "description": "Read all-numeric dates as day/month/year. Default false.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}


def _build(year: int | None, month: int, day: int, matched: str, fmt: str) -> dict:
    if year is None:
        return {
            "date": None,
            "matched_text": matched,
            "format": fmt,
            "note": "no year present in the text; a date cannot be produced",
        }
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        parsed = date(year, month, day)
    except (TypeError, ValueError) as exc:
        return {
            "date": None,
            "matched_text": matched,
            "format": fmt,
            "note": f"not a real calendar date ({exc})",
        }
    return {"date": parsed.isoformat(), "matched_text": matched, "format": fmt}


def _parse_date(text: str, dayfirst: bool) -> dict | None:
    match = _ISO_RE.search(text)
    if match:
        y, m, d = (int(g) for g in match.groups())
        return _build(y, m, d, match.group(0), "iso")

    match = _DMY_RE.search(text)
    if match:
        day = int(match.group(1))
        month = _MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else None
        return _build(year, month, day, match.group(0), "day-month-year")

    match = _MDY_RE.search(text)
    if match:
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        return _build(year, month, day, match.group(0), "month-day-year")

    match = _NUMERIC_RE.search(text)
    if match:
        first, second, year = (int(g) for g in match.groups())
        if dayfirst or first > 12:
            day, month = first, second
        else:
            month, day = first, second
        return _build(year, month, day, match.group(0), "numeric")

    match = _MY_RE.search(text)
    if match:
        month = _MONTHS[match.group(1).lower()]
        return _build(int(match.group(2)), month, 1, match.group(0), "month-year")

    return None


def _parse_time(text: str) -> tuple[str | None, str | None]:
    match = _TIME_RE.search(text)
    if not match:
        return None, None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = (match.group(4) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None, None
    return f"{hour:02d}:{minute:02d}", match.group(5) or None


def run(input: dict) -> str:
    try:
        text = get_str(input, "text")
    except (TypeError, ValueError) as exc:
        return err(f"date_parse: {exc}")
    dayfirst = bool(input.get("dayfirst", False))

    result = _parse_date(text, dayfirst)
    if result is None:
        return err(
            f"date_parse: no date found in {text[:120]!r}. Supported shapes are "
            "'2024-03-07', '7 March 2024', 'March 7, 2024', '03/07/2024' and 'March 2024'."
        )

    clock, timezone = _parse_time(text)
    payload = {"input": text[:200], **result, "time": clock, "timezone": timezone}
    return ok(payload)


def parse_iso_date(text: str, dayfirst: bool = False) -> str | None:
    """Convenience for Python callers: the ISO date string or None."""
    result = _parse_date(text, dayfirst)
    if result is None:
        return None
    return result.get("date")
