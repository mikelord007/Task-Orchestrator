"""backend.architect.generate -- the six-step agent generator (W3 brief, Part 2).

generate() runs, in order: (1) read the evaluator, (2) choose orchestration
mode, (3) draft prompt.md, (4) select tools / write a glue tool, (5) write the
package to disk, (6) apply playbook lessons when asked. Steps 2, 3, 4 and 6
are one STRONG-model call each -- against any object satisfying
``llm_client.CompleteFn`` (a real ``backend.llm.complete``, or
``backend.testing.fake_llm.FakeLLM`` injected via ``backend.llm.set_client``
in tests).

``_finalize`` then validates the written package against ``contracts.agent``
(raising ``PackageError`` on any violation), inserts the ``agents`` row, and
emits ``agent_created``. ``result.finalized`` is ``True`` once that succeeds.
"""

from __future__ import annotations

import os
import sqlite3
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
    evaluators_root: str | Path = "evaluators",
    playbook_path: str | Path = "playbook/lessons.jsonl",
    conn: sqlite3.Connection | None = None,
) -> GenerateResult:
    complete = complete or resolve_complete()
    model = model or os.environ.get(STRONG_MODEL_ENV) or FALLBACK_MODEL

    evaluator = read_evaluator(evaluator_id, root=evaluators_root)
    allowed_tools = steps.filter_known_tools(tools)

    llm_calls: list[dict] = []

    orchestration, response = steps.choose_orchestration(goal, domain, evaluator, complete, model)
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
        # apply_playbook can hand back a prompt that dropped the JSON-output
        # instruction (or never had it) -- re-run the same guarantee draft_prompt
        # gives every prompt.
        prompt_text = steps.ensure_json_output_instruction(
            playbook_result["prompt"], evaluator["expected_keys"]
        )
        applied_lessons = playbook_result["applied_lessons"]
        llm_calls.append({"step": "playbook", **_usage(response)})

    agent_id = package_module.make_agent_id(domain)
    package_dir = package_module.write_package(
        agent_id,
        0,
        domain=domain,
        model_strong=model,
        model_cheap=os.environ.get(CHEAP_MODEL_ENV) or model,
        tools=tool_selection["tools"],
        orchestration=orchestration["mode"],
        orchestration_reason=orchestration["reason"],
        prompt_text=prompt_text,
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
    _finalize(result, evaluator_id=evaluator_id, domain=domain, goal=goal, conn=conn)
    return result


def _finalize(
    result: GenerateResult,
    *,
    evaluator_id: str,
    domain: str,
    goal: str,
    conn: sqlite3.Connection | None,
) -> None:
    """Validate the package, insert the ``agents`` row, emit ``agent_created``.

    ``load_package`` raises ``contracts.agent.PackageError`` (listing every
    violation) if the just-written package does not satisfy the contract --
    this is the acceptance criterion in the brief, so a bad package must fail
    loudly here, not be silently accepted.
    """
    from contracts.agent import load_package

    load_package(result.package_dir)

    from backend.db import init_db, utcnow
    from backend.ledger.emit import emit

    owns_conn = conn is None
    connection = conn or init_db()
    try:
        with connection:
            connection.execute(
                "INSERT INTO agents "
                "(agent_id, goal, domain, evaluator_id, current_version, created_ts) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (result.agent_id, goal, domain, evaluator_id, utcnow()),
            )

        emit(
            "agent_created",
            agent_id=result.agent_id,
            agent_version=0,
            conn=connection,
            payload={
                "goal": goal,
                "domain": domain,
                "tools": result.tools,
                "evaluator_id": evaluator_id,
                "orchestration": result.orchestration["mode"],
                "orchestration_reason": result.orchestration["reason"],
                "applied_lessons": result.applied_lessons,
            },
        )
    finally:
        if owns_conn:
            connection.close()

    result.finalized = True
