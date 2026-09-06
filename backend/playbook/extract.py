"""Distill one general, domain-independent lesson from an accepted fix.

One CHEAP-model call per ``fix_accepted`` (contracts/playbook.md rule 1): given
the fix card's hypothesis, diagnosis, diff summary and before/after numbers,
ask for ``{lever, trigger, lesson, domain_tags[]}`` phrased so a domain that
does not exist yet can still match on it (rule 2). Never asks the agent
anything -- the fix card is the harness's own record, not a self-report.
"""

from __future__ import annotations

import os
from typing import Any

from backend.architect.json_extract import JSONExtractionError, extract_json_object
from backend.architect.llm_client import CompleteFn, resolve_complete

CHEAP_MODEL_ENV = "LLM_MODEL_CHEAP"
FALLBACK_MODEL = "cheap"

# contracts/playbook.md's lever column excludes `grader`: a grader fix corrects
# score.py itself, not the agent, and carries nothing domain-transferable.
ALLOWED_LEVERS = ("prompt", "tools", "memory", "orchestration", "routing")

_JSON_RETRY_HINT = "Reply with ONLY the JSON object described above. No other text, no code fences."

_SYSTEM_PROMPT = """You distill ONE general, domain-independent lesson from a fix that was just \
accepted for an AI agent, so a *different* agent -- in a domain that does not exist yet -- can \
benefit from it later.

Rules:
- Never name the source domain, a specific label, file path, ticket category, or any other \
detail that only makes sense in this one domain. If you can't generalize it, generalize harder.
- `trigger` is the condition under which the lesson applies, phrased so another domain can match \
on it (e.g. "agent must map free-text input to a fixed label vocabulary").
- `lesson` is the actionable instruction itself, generalized the same way.
- `domain_tags` are 1-4 coarse tags such as classification, extraction, triage, tool_use, \
duplicate_detection -- never the literal source domain name.
- `lever` is exactly one of: prompt, tools, memory, orchestration, routing.

Respond with ONLY a JSON object: {"lever": ..., "trigger": ..., "lesson": ..., "domain_tags": [...]}"""


class LessonExtractionError(Exception):
    """The model did not return a usable lesson even after one retry."""


def _fix_card_prompt(fix_card: dict[str, Any]) -> str:
    lines = [
        f"Lever: {fix_card.get('lever')}",
        f"Hypothesis: {fix_card.get('hypothesis')}",
        f"Diagnosis: {fix_card.get('diagnosis')}",
        f"Diff summary: {fix_card.get('diff_summary')}",
    ]
    metric_signal = fix_card.get("metric_signal")
    if metric_signal:
        lines.append(f"Metric signal: {metric_signal}")
    before, after = fix_card.get("before") or {}, fix_card.get("after") or {}
    lines.append(f"Before: {before}")
    lines.append(f"After: {after}")
    return "\n".join(lines)


def _messages(fix_card: dict[str, Any]) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _fix_card_prompt(fix_card)},
    ]


def _clean_domain_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for tag in raw:
        if isinstance(tag, str) and tag.strip():
            normalized = tag.strip().lower()
            if normalized not in tags:
                tags.append(normalized)
    return tags


def _validate(parsed: dict[str, Any], fix_card: dict[str, Any]) -> dict[str, Any]:
    lever = parsed.get("lever")
    if lever not in ALLOWED_LEVERS:
        # Fail safe to the fix's own lever rather than discarding a usable
        # lesson over a model that forgot the enum.
        lever = fix_card.get("lever") if fix_card.get("lever") in ALLOWED_LEVERS else None
    trigger = parsed.get("trigger")
    lesson = parsed.get("lesson")
    if lever is None or not isinstance(trigger, str) or not trigger.strip():
        raise LessonExtractionError(f"unusable lesson extraction result: {parsed!r}")
    if not isinstance(lesson, str) or not lesson.strip():
        raise LessonExtractionError(f"unusable lesson extraction result: {parsed!r}")
    return {
        "lever": lever,
        "trigger": trigger.strip(),
        "lesson": lesson.strip(),
        "domain_tags": _clean_domain_tags(parsed.get("domain_tags")),
    }


def extract_lesson(
    fix_card: dict[str, Any],
    *,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``({lever, trigger, lesson, domain_tags[]}, raw_llm_response)``.

    Raises :class:`LessonExtractionError` if the model's output can't be used
    even after one retry with a stricter hint (mirrors
    ``backend.architect.steps._complete_json``).
    """
    complete = complete or resolve_complete()
    model = model or os.environ.get(CHEAP_MODEL_ENV) or FALLBACK_MODEL
    messages = _messages(fix_card)

    response = complete(messages=messages, model=model)
    try:
        parsed = extract_json_object(response.get("text", ""))
        return _validate(parsed, fix_card), response
    except (JSONExtractionError, LessonExtractionError):
        pass

    retried = [*messages, {"role": "user", "content": _JSON_RETRY_HINT}]
    response = complete(messages=retried, model=model)
    try:
        parsed = extract_json_object(response.get("text", ""))
    except JSONExtractionError as exc:
        raise LessonExtractionError(f"the model did not return usable JSON: {exc}") from exc
    return _validate(parsed, fix_card), response
