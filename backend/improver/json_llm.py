"""One-STRONG-call-with-a-retry helper shared by `reflect` and `diagnose`.

Mirrors `backend.architect.steps._complete_json`: ask for JSON, and if the
model wraps it in prose or fences, retry once with a blunt instruction before
giving up. Every LLM call in this package goes through `backend.llm.complete`
(or a test's injected `CompleteFn`) -- never a second, ad hoc client.
"""

from __future__ import annotations

from typing import Any

from backend.architect.json_extract import JSONExtractionError, extract_json_object
from backend.architect.llm_client import CompleteFn, resolve_complete

__all__ = ["JsonCallError", "complete_json"]

_RETRY_HINT = "Reply with ONLY the JSON object described above. No other text, no code fences."


class JsonCallError(RuntimeError):
    """The model did not return usable JSON even after one retry."""


def complete_json(
    messages: list[dict[str, Any]],
    model: str,
    *,
    complete: CompleteFn | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the model and parse its text as one JSON object.

    Returns `(parsed, raw_response)`. `raw_response` is `backend.llm.complete`'s
    full return value (text/tool_calls/usage/cost_usd/...), in case a caller
    wants to report cost -- reflection and diagnosis calls are LLM spend too.
    """
    complete = complete or resolve_complete()
    response = complete(messages=messages, model=model)
    try:
        return extract_json_object(response.get("text", "")), response
    except JSONExtractionError:
        pass

    retried = [*messages, {"role": "user", "content": _RETRY_HINT}]
    response = complete(messages=retried, model=model)
    try:
        return extract_json_object(response.get("text", "")), response
    except JSONExtractionError as exc:
        raise JsonCallError(f"the model did not return usable JSON: {exc}") from exc
