"""Single LLM access point (PLAN.md section 3).

Every model call in the system goes through `complete()`. It returns text, tool
calls, usage **taken from the API response** (never from the model's own claim),
and the cost derived from `COST_TABLE`.

Configuration (see `.env.example`):

    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_STRONG, LLM_MODEL_CHEAP

Tests never hit the network: `backend.testing.fake_llm.FakeLLM` is injected with
`set_client()`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ModelCost",
    "COST_TABLE",
    "MODEL_STRONG",
    "MODEL_CHEAP",
    "LLMError",
    "complete",
    "cost_for",
    "model_for_tier",
    "get_client",
    "set_client",
    "reset_client",
    "to_openai_tools",
]


class LLMError(RuntimeError):
    """Raised when the LLM endpoint is unusable (missing config, API failure)."""


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


MODEL_STRONG = _env("LLM_MODEL_STRONG", "gpt-4o")
MODEL_CHEAP = _env("LLM_MODEL_CHEAP", "gpt-4o-mini")


@dataclass(frozen=True)
class ModelCost:
    """USD per 1M tokens."""

    usd_per_mtok_in: float
    usd_per_mtok_out: float


# List prices at build time, in USD per 1M tokens. These are *defaults*: any
# deployment pointing LLM_BASE_URL at a different provider must override them
# via LLM_COST_TABLE so no cost number in the ledger is invented.
#
#   LLM_COST_TABLE='{"my-model": {"in": 1.0, "out": 3.0}}'
#
# An unpriced model costs LLM_COST_DEFAULT_IN / _OUT (0.0 unless set) rather
# than a guessed number.
_BUILTIN_COSTS: dict[str, ModelCost] = {
    "gpt-4o": ModelCost(2.50, 10.00),
    "gpt-4o-mini": ModelCost(0.15, 0.60),
    "gpt-4.1": ModelCost(2.00, 8.00),
    "gpt-4.1-mini": ModelCost(0.40, 1.60),
    "gpt-4.1-nano": ModelCost(0.10, 0.40),
}


def _load_cost_table() -> dict[str, ModelCost]:
    table = dict(_BUILTIN_COSTS)
    raw = os.environ.get("LLM_COST_TABLE")
    if raw:
        try:
            override = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM_COST_TABLE is not valid JSON: {exc}") from exc
        for model, entry in override.items():
            table[model] = ModelCost(float(entry["in"]), float(entry["out"]))
    return table


COST_TABLE: dict[str, ModelCost] = _load_cost_table()


def cost_for(model: str, tokens_in: int, tokens_out: int) -> float:
    """USD cost of one call, from COST_TABLE. Unknown model -> the env default."""
    entry = COST_TABLE.get(model)
    if entry is None:
        entry = ModelCost(
            float(_env("LLM_COST_DEFAULT_IN", "0")),
            float(_env("LLM_COST_DEFAULT_OUT", "0")),
        )
    return round(
        tokens_in / 1_000_000 * entry.usd_per_mtok_in
        + tokens_out / 1_000_000 * entry.usd_per_mtok_out,
        8,
    )


def model_for_tier(tier: str) -> str:
    """Map `strong` / `cheap` (agent.yaml routing) to a concrete model id."""
    if tier == "cheap":
        return MODEL_CHEAP
    if tier == "strong":
        return MODEL_STRONG
    raise LLMError(f"unknown model tier {tier!r}; expected 'strong' or 'cheap'")


# --------------------------------------------------------------------------
# Client (injectable)
# --------------------------------------------------------------------------

_client: Any | None = None


def set_client(client: Any) -> None:
    """Inject a client. Tests pass `FakeLLM()`; nothing else may hit the network."""
    global _client
    _client = client


def reset_client() -> None:
    """Drop the injected/cached client so the next call rebuilds a real one."""
    global _client
    _client = None


def get_client() -> Any:
    """Return the injected client, or build an OpenAI-compatible one from env."""
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMError(
            "LLM_API_KEY is not set. Set it in .env, or inject a test double "
            "with backend.llm.set_client(FakeLLM(...))."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMError("the `openai` package is required for live LLM calls") from exc
    _client = OpenAI(base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"), api_key=api_key)
    return _client


# --------------------------------------------------------------------------
# Tool schema normalization
# --------------------------------------------------------------------------


def to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Accept contract `TOOL` dicts or already-OpenAI tool dicts; emit OpenAI shape.

    Contract shape (contracts/agent.py `ToolSpec`)::

        {"name": ..., "description": ..., "input_schema": {...}}
    """
    if not tools:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") == "function" and "function" in tool:
            out.append(tool)
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _parse_tool_calls(message: Any) -> list[dict[str, Any]]:
    raw_calls = getattr(message, "tool_calls", None) or []
    calls: list[dict[str, Any]] = []
    for call in raw_calls:
        fn = getattr(call, "function", None)
        raw_args = getattr(fn, "arguments", "") or ""
        try:
            arguments = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            arguments = {}
        calls.append(
            {
                "id": getattr(call, "id", None),
                "name": getattr(fn, "name", None),
                "arguments": arguments,
                "arguments_raw": raw_args,
            }
        )
    return calls


# --------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------


def complete(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]] | None = None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    """One chat completion.

    Returns::

        {"text": str,
         "tool_calls": [{"id", "name", "arguments": dict, "arguments_raw": str}],
         "usage": {"tokens_in": int, "tokens_out": int},
         "cost_usd": float,
         "model": str,
         "finish_reason": str | None,
         "latency_ms": int}

    `usage` comes from the API response, never from the model's own words
    (rule section 2.8).
    """
    client = get_client()
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    openai_tools = to_openai_tools(tools)
    if openai_tools:
        kwargs["tools"] = openai_tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 - surface every provider error the same way
        raise LLMError(f"LLM call to {model!r} failed: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    choice = response.choices[0]
    message = choice.message
    usage = getattr(response, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)

    return {
        "text": getattr(message, "content", None) or "",
        "tool_calls": _parse_tool_calls(message),
        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
        "cost_usd": cost_for(model, tokens_in, tokens_out),
        "model": getattr(response, "model", model) or model,
        "finish_reason": getattr(choice, "finish_reason", None),
        "latency_ms": latency_ms,
    }
