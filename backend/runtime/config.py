"""Runtime knobs.

Read from the environment at call time so tests can monkeypatch, and passed
around explicitly as a frozen :class:`Knobs` so nothing reads globals mid-run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_EVAL_TRIALS = 3
DEFAULT_EVAL_CONCURRENCY = 4
DEFAULT_DRIFT_MAX_STEPS = 12
DEFAULT_DRIFT_TOKEN_BUDGET = 20_000
DEFAULT_DRIFT_REPEAT_CALL_LIMIT = 3
DEFAULT_CASE_TIMEOUT_S = 120
DEFAULT_MEMORY_TOP_K = 12
DEFAULT_MEMORY_MIN_USES = 4


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Knobs:
    eval_trials: int = DEFAULT_EVAL_TRIALS
    eval_concurrency: int = DEFAULT_EVAL_CONCURRENCY
    drift_max_steps: int = DEFAULT_DRIFT_MAX_STEPS
    drift_token_budget: int = DEFAULT_DRIFT_TOKEN_BUDGET
    drift_repeat_call_limit: int = DEFAULT_DRIFT_REPEAT_CALL_LIMIT
    case_timeout_s: int = DEFAULT_CASE_TIMEOUT_S
    memory_top_k: int = DEFAULT_MEMORY_TOP_K
    memory_min_uses: int = DEFAULT_MEMORY_MIN_USES


def load_knobs() -> Knobs:
    """Build a :class:`Knobs` from the current environment.

    ``EVAL_TRIALS`` is canonical; ``EVAL_REPEATS`` is accepted as a deprecated
    fallback alias (PLAN_ADDENDUM.md section A) for anyone still setting it.
    """
    eval_trials_default = _int_env("EVAL_REPEATS", DEFAULT_EVAL_TRIALS)
    return Knobs(
        eval_trials=_int_env("EVAL_TRIALS", eval_trials_default),
        eval_concurrency=_int_env("EVAL_CONCURRENCY", DEFAULT_EVAL_CONCURRENCY),
        drift_max_steps=_int_env("DRIFT_MAX_STEPS", DEFAULT_DRIFT_MAX_STEPS),
        drift_token_budget=_int_env("DRIFT_TOKEN_BUDGET", DEFAULT_DRIFT_TOKEN_BUDGET),
        drift_repeat_call_limit=_int_env(
            "DRIFT_REPEAT_CALL_LIMIT", DEFAULT_DRIFT_REPEAT_CALL_LIMIT
        ),
        case_timeout_s=_int_env("CASE_TIMEOUT_S", DEFAULT_CASE_TIMEOUT_S),
        memory_top_k=_int_env("MEMORY_TOP_K", DEFAULT_MEMORY_TOP_K),
        memory_min_uses=_int_env("MEMORY_MIN_USES", DEFAULT_MEMORY_MIN_USES),
    )
