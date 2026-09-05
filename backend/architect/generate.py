"""backend.architect.generate -- the six-step agent generator (W3 brief, Part 2).

generate() runs, in order: (1) read the evaluator, (2) choose orchestration
mode, (3) draft prompt.md, (4) select tools / write a glue tool, (5) write the
package to disk, (6) apply playbook lessons when asked. Steps 2, 3, 4 and 6
are one STRONG-model call each.

Everything above works today against any object satisfying
``llm_client.CompleteFn``. What is deliberately deferred until Phase 0 lands
on ``main`` (``contracts.agent``, ``backend.db``, ``backend.ledger.emit``) is
guarded behind lazy imports in ``_finalize``: validating the written package,
inserting the ``agents`` row, and emitting ``agent_created``. Until then,
``generate()`` still returns a full ``GenerateResult`` with the package
written to disk; ``result.finalized`` is ``False`` and the caller can inspect
the package directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import package as package_module
from . import steps
from .evaluator_reader import read_evaluator
from .llm_client import CompleteFn, resolve_complete
from .playbook_reader import read_lessons, select_relevant_lessons

STRONG_MODEL_ENV = "LLM_MODEL_STRONG"
CHEAP_MODEL_ENV = "LLM_MODEL_CHEAP"
FALLBACK_MODEL = "strong"


@dataclass
class GenerateResult:
    agent_id: str
    version: int
    package_dir: Path
    orchestration: dict
    tools: list[str]
    glue_tool: dict | None
    applied_lessons: list[str]
    prompt_text: str
    llm_calls: list[dict] = field(default_factory=list)
    finalized: bool = False


def _usage(response: dict) -> dict:
    usage = response.get("usage") or {}
    return {
        "tokens_in": usage.get("tokens_in"),
        "tokens_out": usage.get("tokens_out"),
        "cost_usd": response.get("cost_usd"),
    }


def generate(
    goal: str,
    domain: str,
    tools: list[str],
    evaluator_id: str,
    use_playbook: bool = False,
    *,
    complete: CompleteFn | None = None,
    model: str | None = None,
    agents_root: str | Path = package_module.DEFAULT_AGENTS_ROOT,
    evaluators_root: str = "evaluators",
    playbook_path: str = "playbook/lessons.jsonl",
) -> GenerateResult:
    complete = complete or resolve_complete()
    model = model or os.environ.get(STRONG_MODEL_ENV) or FALLBACK_MODEL

    evaluator = read_evaluator(evaluator_id, root=evaluators_root)
    allowed_tools = steps.filter_known_tools(tools)

    llm_calls: list[dict] = []

    orchestration, response = steps.choose_orchestration(
        goal, domain, evaluator, complete, model
    )
    llm_calls.append({"step": "orchestration", **_usage(response)})

    prompt_text, response = steps.draft_prompt(
        goal, domain, evaluator, orchestration, complete, model
    )
    llm_calls.append({"step": "prompt", **_usage(response)})

    tool_selection, response = steps.select_tools(
        goal, domain, evaluator, allowed_tools, complete, model
    )
    llm_calls.append({"step": "tools", **_usage(response)})

    applied_lessons: list[str] = []
    if use_playbook:
        lessons = select_relevant_lessons(read_lessons(playbook_path), domain, goal)
        playbook_result, response = steps.apply_playbook(
            goal, domain, prompt_text, lessons, complete, model
        )
        prompt_text = playbook_result["prompt"]
        applied_lessons = playbook_result["applied_lessons"]
        llm_calls.append({"step": "playbook", **_usage(response)})

    agent_id = package_module.make_agent_id(domain)
    package_dir = package_module.write_package(
        agent_id,
        0,
        goal=goal,
        domain=domain,
        evaluator_id=evaluator_id,
        model_strong=model,
        model_cheap=os.environ.get(CHEAP_MODEL_ENV) or model,
        tools=tool_selection["tools"],
        orchestration=orchestration["mode"],
        orchestration_reason=orchestration["reason"],
        prompt_text=prompt_text,
        applied_lessons=applied_lessons,
        glue_tool=tool_selection["glue_tool"],
        root=agents_root,
    )

    result = GenerateResult(
        agent_id=agent_id,
        version=0,
        package_dir=package_dir,
        orchestration=orchestration,
        tools=tool_selection["tools"],
        glue_tool=tool_selection["glue_tool"],
        applied_lessons=applied_lessons,
        prompt_text=prompt_text,
        llm_calls=llm_calls,
    )
    _finalize(result, evaluator_id=evaluator_id, domain=domain, goal=goal)
    return result


def _finalize(
    result: GenerateResult, *, evaluator_id: str, domain: str, goal: str
) -> None:
    """Validate the package, insert the ``agents`` row, emit ``agent_created``.

    TODO(Phase 0 merge): both imports below currently fail because
    ``contracts.agent``, ``backend.db`` and ``backend.ledger.emit`` are not on
    this branch yet, so this function is a deliberate no-op today. Once Phase
    0 merges: drop the try/except ImportError guards (a missing contract
    should be a hard failure, not a silent skip), replace the placeholder SQL
    with whatever `backend.db` actually exposes, and emit every key
    `contracts/events.py` requires for `agent_created` (goal, domain, tools,
    evaluator_id, orchestration, applied_lessons).
    """
    try:
        from contracts.agent import validate_package  # type: ignore[import-not-found]
    except ImportError:
        return

    validate_package(result.package_dir)

    try:
        from backend.db import get_connection  # type: ignore[import-not-found]
        from backend.ledger.emit import emit  # type: ignore[import-not-found]
    except ImportError:
        return

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agents (agent_id, goal, domain, evaluator_id, current_version, created_ts) "
            "VALUES (?, ?, ?, ?, 0, datetime('now'))",
            (result.agent_id, goal, domain, evaluator_id),
        )
        conn.commit()

    emit(
        kind="agent_created",
        agent_id=result.agent_id,
        agent_version=0,
        payload={
            "goal": goal,
            "domain": domain,
            "tools": result.tools,
            "evaluator_id": evaluator_id,
            "orchestration": result.orchestration["mode"],
            "applied_lessons": result.applied_lessons,
        },
    )
    result.finalized = True
