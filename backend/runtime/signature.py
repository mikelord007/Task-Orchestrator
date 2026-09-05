"""Failure signatures.

A ``failure_signature`` is a normalized string derived from *observed* facts —
the evaluator's score notes, the first tool error the harness recorded, and the
expected output keys the agent did not produce. Normalization (lowercase,
numbers stripped, whitespace collapsed, capped length) is what makes identical
failures dedupe across runs so the improver can group them.
"""

from __future__ import annotations

import re
from typing import Any

MAX_SIGNATURE_LEN = 120
DRIFT_SIGNATURE_PREFIX = "drift:"
UNKNOWN_SIGNATURE = "unknown_failure"
BAD_OUTPUT_SIGNATURE = "bad_output"

_NUMBERS = re.compile(r"\d+")
_NON_SIGNIFICANT = re.compile(r"[^a-z0-9|,_ ]+")
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.lower()
    text = _NUMBERS.sub(" ", text)
    text = _NON_SIGNIFICANT.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


def failure_signature(
    score_notes: str | None = None,
    first_tool_error: str | None = None,
    missing_keys: list[str] | None = None,
) -> str:
    """Normalized signature built from the three observed failure inputs."""
    parts: list[str] = []
    notes = _normalize(score_notes or "")
    if notes:
        parts.append(notes)
    tool_error = _normalize(first_tool_error or "")
    if tool_error:
        parts.append(f"tool_error {tool_error}")
    if missing_keys:
        keys = sorted(
            {_normalize(str(k)).replace(" ", "_") for k in missing_keys if str(k).strip()}
        )
        keys = [k for k in keys if k]
        if keys:
            parts.append("missing " + ",".join(keys))
    if not parts:
        return UNKNOWN_SIGNATURE
    return " | ".join(parts)[:MAX_SIGNATURE_LEN].strip()


def drift_signature(kind: str) -> str:
    """Signature for a case aborted by the drift watchdog."""
    return f"{DRIFT_SIGNATURE_PREFIX}{kind}"


def bad_output_signature() -> str:
    """Signature for a final answer that could not be parsed as JSON."""
    return BAD_OUTPUT_SIGNATURE


def missing_expected_keys(expected: dict[str, Any], actual: Any) -> list[str]:
    """Expected top-level keys the agent's output did not supply (sorted)."""
    if not isinstance(expected, dict):
        return []
    if not isinstance(actual, dict):
        return sorted(str(k) for k in expected)
    return sorted(str(k) for k in expected if k not in actual or actual.get(k) is None)
