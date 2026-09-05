"""Per-case runtime context available to tools.

The runtime sets `current_case` to the evaluator case dict before running each
case, so a tool can see *which* case it is serving without that being threaded
through every call signature.

The reason this exists: the `github_triage` tools read live/cached GitHub data
for an issue whose **ground-truth labels are the expected answer**. A tool must
redact those before returning, or the agent reads the answer off the tool
output and every score is meaningless. `current_case` is how a tool knows what
to redact.

    # backend/toolbox/github.py
    from contracts.context import current_case

    def run(input: dict) -> str:
        case = current_case.get()
        target = (case or {}).get("input", {}).get("number")
        ...  # strip labels/assignees from issue `target` before returning

Rules:

* The runtime **sets and resets** it around each case; nothing else writes it.
* It is a `ContextVar`, so it is safe under the eval harness's bounded
  concurrency: each task sees its own value, and the default is `None`.
* A tool must tolerate `None` (it is `None` outside a case, e.g. when the
  architect smoke-tests a generated tool).
* It carries the **case**, not the agent's state. It is not a memory channel
  and not a way for a tool to report what it did (rule section 2.8).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

__all__ = ["current_case", "case_scope"]

current_case: ContextVar[dict[str, Any] | None] = ContextVar("current_case", default=None)


@contextmanager
def case_scope(case: dict[str, Any] | None) -> Iterator[None]:
    """Set `current_case` for the duration of one case, then restore it."""
    token = current_case.set(case)
    try:
        yield
    finally:
        current_case.reset(token)
