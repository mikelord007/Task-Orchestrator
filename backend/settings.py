"""Centralized environment access.

Loads `.env` once, here, via `python-dotenv` (`load_dotenv()` is a no-op if
the file is absent, and it never overrides a variable already set in the real
environment). Import this instead of reading `os.environ` directly in new
code: it guarantees `.env` is loaded, and it keeps env reads as plain function
calls rather than module-level constants, so tests can `monkeypatch.setenv`
and see the new value on the next call (see `backend/llm.py` for why that
laziness matters).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

__all__ = ["env", "env_int", "env_float", "eval_trials"]


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value else default


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


def eval_trials(default: int = 3) -> int:
    """`EVAL_TRIALS`, falling back to the deprecated `EVAL_REPEATS` alias."""
    raw = os.environ.get("EVAL_TRIALS") or os.environ.get("EVAL_REPEATS")
    return int(raw) if raw else default
