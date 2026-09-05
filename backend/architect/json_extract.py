"""Extract a single JSON object from an LLM text response."""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class JSONExtractionError(ValueError):
    pass


def extract_json_object(text: str) -> dict:
    """Parse ``text`` as a JSON object, tolerating a fenced block or stray prose around it."""
    candidate = (text or "").strip()
    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JSONExtractionError(
            f"could not parse a JSON object from the response ({exc})"
        ) from exc
    if not isinstance(parsed, dict):
        raise JSONExtractionError(
            f"expected a JSON object, got {type(parsed).__name__}"
        )
    return parsed
