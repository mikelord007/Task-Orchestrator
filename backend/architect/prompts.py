"""Prompt builders for the architect's LLM-backed steps.

One STRONG-model call per step (orchestration, prompt drafting, tool
selection, and -- only when ``use_playbook`` -- applying playbook lessons).
"""

from __future__ import annotations

import json


def _render_samples(sample_cases: list[dict], limit: int = 5) -> str:
    rendered = [
        json.dumps(
            {
                "id": case.get("id"),
                "input": case.get("input"),
                "expected": case.get("expected"),
                "tags": case.get("tags"),
            },
            indent=2,
            default=str,
        )
        for case in sample_cases[:limit]
    ]
    return "\n\n".join(rendered) if rendered else "(no sample cases available)"


def orchestration_prompt(goal: str, domain: str, evaluator: dict) -> list[dict]:
    system = (
        "You are designing the architecture for a new AI agent. You choose "
        "exactly one orchestration mode and justify it in one paragraph. "
        'Reply with ONLY a JSON object: {"mode": "single"|"planner_worker", '
        '"reason": "<one paragraph>"}. No prose outside the JSON.'
    )
    user = (
        f"Goal: {goal}\nDomain: {domain}\n\n"
        f"Evaluator README:\n{evaluator['readme']}\n\n"
        f"Sample train cases:\n{_render_samples(evaluator['sample_cases'])}\n\n"
        "Choose 'single' if one model call per case, with tools, is sufficient. "
        "Choose 'planner_worker' only if the task clearly benefits from a "
        "separate planning pass before acting -- multi-step tool orchestration "
        "across several sub-decisions, or genuinely ambiguous subgoals that "
        "need to be broken down first. Justify your choice using specifics "
        "from the evaluator README and samples above, not generic reasoning."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def prompt_draft_prompt(
    goal: str, domain: str, evaluator: dict, orchestration: dict
) -> list[dict]:
    system = (
        "You write the system prompt for a new AI agent. Reply with ONLY the "
        "system prompt text itself, in Markdown -- no surrounding commentary, "
        "no JSON, no code fences."
    )
    keys = evaluator["expected_keys"] or ["result"]
    user = (
        f"Goal: {goal}\nDomain: {domain}\n"
        f"Orchestration mode: {orchestration['mode']} ({orchestration['reason']})\n\n"
        f"Evaluator README:\n{evaluator['readme']}\n\n"
        f"Sample train cases:\n{_render_samples(evaluator['sample_cases'])}\n\n"
        "Write the system prompt for this agent. It MUST instruct the agent to "
        "answer with a single JSON object as its final output, with exactly "
        f"these top-level keys: {keys}. Explain what each key means in this "
        "domain, mention that it has tools available without listing exact "
        "tool names (those are supplied separately at runtime), and give "
        "concrete guidance drawn from the evaluator README and sample cases "
        "above -- what 'good' looks like here, and common failure modes to "
        "avoid."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def tool_selection_prompt(
    goal: str, domain: str, evaluator: dict, allowed_tools: list[str]
) -> list[dict]:
    system = (
        "You select which tools a new agent should be given, from a fixed "
        "allow-list, and decide whether it also needs one small custom tool "
        "the allow-list cannot provide. Reply with ONLY a JSON object: "
        '{"tools": [<names from the allow-list you are given, choose a '
        'subset>], "glue_tool": null | {"name": "<snake_case identifier, not '
        'one of the allow-listed names>", "description": "<what it does, '
        'when to use it, what it does NOT do>", "code": "<a complete Python '
        "module defining TOOL = {'name', 'description', 'input_schema'} and "
        'def run(input: dict) -> str, self-contained, stdlib only>", '
        '"test_code": "<a complete pytest module that loads the sibling '
        "module by file path with importlib (do not use a relative import) "
        'and asserts run() behaves correctly on at least one example>"}}. '
        "Only propose a glue_tool if none of the allowed tools, used directly "
        "or in sequence, can produce what this task needs -- most tasks do "
        "not need one; when in doubt, use null."
    )
    user = (
        f"Goal: {goal}\nDomain: {domain}\n\n"
        f"Allowed tools (choose a subset, do not invent names): {allowed_tools}\n\n"
        f"Evaluator README:\n{evaluator['readme']}\n\n"
        f"Sample train cases:\n{_render_samples(evaluator['sample_cases'])}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def playbook_prompt(
    goal: str, domain: str, prompt_text: str, lessons: list[dict]
) -> list[dict]:
    system = (
        "You revise an agent's system prompt to incorporate relevant lessons "
        "learned from improving other agents, possibly in other domains. "
        'Reply with ONLY a JSON object: {"prompt": "<revised full system '
        'prompt>", "applied_lesson_ids": [<ids of lessons you actually '
        "incorporated>]}. Preserve everything in the current prompt that "
        "still holds; only add or adjust guidance a lesson supports. Do not "
        "apply a lesson that does not clearly transfer to this domain -- "
        "leave applied_lesson_ids empty if none apply, and return the prompt "
        "unchanged in that case."
    )
    rendered_lessons = (
        json.dumps(lessons, indent=2, default=str)
        if lessons
        else "(no lessons recorded yet)"
    )
    user = (
        f"Goal: {goal}\nDomain: {domain}\n\nCurrent system prompt:\n{prompt_text}\n\n"
        f"Candidate lessons from the playbook:\n{rendered_lessons}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
