"""Extract a single JSON object from an LLM text response."""

from __future__ import annotations

import json
import re

# Two fence readings, tried in order (see `_candidates`).  The greedy pattern
# runs to the *last* closing fence, which is what a generated `prompt` value
# needs: those routinely embed their own ```json output-format example, and a
# non-greedy match would stop at that nested fence and truncate the object
# mid-string.  The non-greedy pattern stays as the fallback for a reply that
# puts a second, unrelated fenced block after the JSON one.
_FENCE_GREEDY_RE = re.compile(r"```(?:json)?\s*(.*)\s*```", re.DOTALL | re.IGNORECASE)
_FENCE_LAZY_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class JSONExtractionError(ValueError):
    pass


def _candidates(text: str) -> list[str]:
    """Plausible JSON substrings of ``text``, best-first."""
    candidate = (text or "").strip()
    out: list[str] = []
    for pattern in (_FENCE_GREEDY_RE, _FENCE_LAZY_RE):
        fence = pattern.search(candidate)
        if fence:
            inner = fence.group(1).strip()
            if inner and inner not in out:
                out.append(inner)

    # Try the complete response before repairing prose with a brace slice.  If
    # it is valid non-object JSON, the caller should reject it as-is instead of
    # accepting an object nested inside it (for example, [{"a": 1}]).
    if candidate not in out:
        out.append(candidate)

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        sliced = candidate[start : end + 1]
        if sliced not in out:
            out.append(sliced)
    return out


def extract_json_object(text: str) -> dict:
    """Parse ``text`` as a JSON object, tolerating a fenced block or stray prose around it."""
    first_error: json.JSONDecodeError | None = None
    for candidate in _candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            if first_error is None:
                first_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        raise JSONExtractionError(f"expected a JSON object, got {type(parsed).__name__}")

    raise JSONExtractionError(
        f"could not parse a JSON object from the response ({first_error})"
    ) from first_error
