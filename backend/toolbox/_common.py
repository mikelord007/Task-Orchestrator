"""Shared helpers for tool modules. Not a tool itself."""

from __future__ import annotations

import json
from typing import Any

ERROR_PREFIX = "ERROR:"


def ok(payload: Any) -> str:
    """JSON-encode a successful structured result."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=False, default=str)


def err(message: str) -> str:
    """Format a failure the agent is expected to read and react to."""
    return f"{ERROR_PREFIX} {message}"


def is_error(result: str) -> bool:
    return result.startswith(ERROR_PREFIX)


def get_str(payload: dict, key: str, *, required: bool = True, default: str = "") -> str:
    value = payload.get(key, None)
    if value is None:
        if required:
            raise ValueError(f"missing required argument {key!r}")
        return default
    if not isinstance(value, str):
        raise TypeError(f"argument {key!r} must be a string, got {type(value).__name__}")
    return value


def get_int(
    payload: dict,
    key: str,
    *,
    required: bool = True,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = payload.get(key, None)
    if value is None:
        if required:
            raise ValueError(f"missing required argument {key!r}")
        value = default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"argument {key!r} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"argument {key!r} must be an integer, got {value!r}") from None
    if minimum is not None and value < minimum:
        raise ValueError(f"argument {key!r} must be >= {minimum}, got {value}")
    if maximum is not None:
        value = min(value, maximum)
    return value


def truncate(text: str | None, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters, marking that it was cut."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} more characters]"
