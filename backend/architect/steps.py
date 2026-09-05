"""The architect's LLM-backed steps (2, 3, 4, and 6 when use_playbook)."""

from __future__ import annotations

import ast

from . import prompts
from .json_extract import JSONExtractionError, extract_json_object
from .llm_client import CompleteFn

ORCHESTRATION_MODES = {"single", "planner_worker"}

_JSON_RETRY_HINT = (
    "Reply with ONLY the JSON object described above. No other text, no code fences."
)


class ArchitectStepError(Exception):
    """A step's LLM output could not be used even after one retry."""


def filter_known_tools(tools: list[str]) -> list[str]:
    """The subset of ``tools`` that exist in the toolbox, in the given order."""
    from toolbox import registry as toolbox_registry

    known = [name for name in tools if name in toolbox_registry.TOOLBOX]
    if not known:
        raise ArchitectStepError(
            f"none of the requested tools {tools!r} exist in the toolbox; "
            "an agent needs at least one real tool to work with"
        )
    return known


def _complete_json(
    complete: CompleteFn, messages: list[dict], model: str
) -> tuple[dict, dict]:
    response = complete(messages=messages, model=model)
    try:
        return extract_json_object(response.get("text", "")), response
    except JSONExtractionError:
        pass

    retried_messages = [*messages, {"role": "user", "content": _JSON_RETRY_HINT}]
    response = complete(messages=retried_messages, model=model)
    try:
        return extract_json_object(response.get("text", "")), response
    except JSONExtractionError as exc:
        raise ArchitectStepError(
            f"the model did not return usable JSON: {exc}"
        ) from exc


def choose_orchestration(
    goal: str, domain: str, evaluator: dict, complete: CompleteFn, model: str
) -> tuple[dict, dict]:
    messages = prompts.orchestration_prompt(goal, domain, evaluator)
    parsed, response = _complete_json(complete, messages, model)

    mode = parsed.get("mode")
    reason = parsed.get("reason")
    if (
        mode not in ORCHESTRATION_MODES
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise ArchitectStepError(
            f"orchestration step returned an unusable result: {parsed!r}"
        )
    return {"mode": mode, "reason": reason.strip()}, response


def _ensure_json_output_instruction(prompt_text: str, expected_keys: list[str]) -> str:
    keys = expected_keys or ["result"]
    if "json" in prompt_text.lower() and all(key in prompt_text for key in keys):
        return prompt_text
    footer = (
        "\n\n## Output format\n\n"
        "Respond with a single JSON object as your final answer, with exactly "
        f"these top-level keys: {keys}. Do not include any text outside the "
        "JSON object."
    )
    return prompt_text.rstrip() + footer


def draft_prompt(
    goal: str,
    domain: str,
    evaluator: dict,
    orchestration: dict,
    complete: CompleteFn,
    model: str,
) -> tuple[str, dict]:
    messages = prompts.prompt_draft_prompt(goal, domain, evaluator, orchestration)
    response = complete(messages=messages, model=model)
    text = (response.get("text") or "").strip()
    if not text:
        raise ArchitectStepError("prompt drafting step returned empty text")
    return _ensure_json_output_instruction(text, evaluator["expected_keys"]), response


def _valid_glue_tool(glue_tool: object, allowed_tools: list[str]) -> bool:
    from toolbox import registry as toolbox_registry

    if not isinstance(glue_tool, dict):
        return False
    name = glue_tool.get("name")
    code = glue_tool.get("code")
    test_code = glue_tool.get("test_code")
    if not (isinstance(name, str) and name.isidentifier()):
        return False
    if name in allowed_tools or name in toolbox_registry.TOOLBOX:
        return False
    if not isinstance(code, str) or not code.strip():
        return False
    if not isinstance(test_code, str) or not test_code.strip():
        return False
    try:
        ast.parse(code)
        ast.parse(test_code)
    except SyntaxError:
        return False
    return True


def select_tools(
    goal: str,
    domain: str,
    evaluator: dict,
    allowed_tools: list[str],
    complete: CompleteFn,
    model: str,
) -> tuple[dict, dict]:
    if not allowed_tools:
        raise ArchitectStepError("no tools were allow-listed for this agent")

    messages = prompts.tool_selection_prompt(goal, domain, evaluator, allowed_tools)
    parsed, response = _complete_json(complete, messages, model)

    selected = [name for name in (parsed.get("tools") or []) if name in allowed_tools]
    if not selected:
        # Fail safe rather than fail closed: never ship a tool-less agent
        # because the model's selection didn't parse cleanly.
        selected = list(allowed_tools)

    glue_tool = parsed.get("glue_tool") or None
    if glue_tool is not None and not _valid_glue_tool(glue_tool, allowed_tools):
        glue_tool = None

    return {"tools": selected, "glue_tool": glue_tool}, response


def apply_playbook(
    goal: str,
    domain: str,
    prompt_text: str,
    lessons: list[dict],
    complete: CompleteFn,
    model: str,
) -> tuple[dict, dict]:
    messages = prompts.playbook_prompt(goal, domain, prompt_text, lessons)
    parsed, response = _complete_json(complete, messages, model)

    revised_prompt = parsed.get("prompt")
    if not isinstance(revised_prompt, str) or not revised_prompt.strip():
        return {"prompt": prompt_text, "applied_lessons": []}, response

    known_ids = {lesson.get("id") for lesson in lessons}
    applied_ids = [
        lesson_id
        for lesson_id in (parsed.get("applied_lesson_ids") or [])
        if isinstance(lesson_id, str) and lesson_id in known_ids
    ]
    return {"prompt": revised_prompt.strip(), "applied_lessons": applied_ids}, response
