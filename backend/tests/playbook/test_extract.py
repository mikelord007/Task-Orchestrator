from __future__ import annotations

import json

import pytest

from backend.playbook.extract import LessonExtractionError, extract_lesson

FIX_CARD = {
    "lever": "memory",
    "hypothesis": "The agent never learned that src/pty/ paths belong to the pty component.",
    "diagnosis": "Windows/ConPTY issues get component=core: no rule maps paths to components.",
    "diff_summary": "+3 rules, +1 tool note",
    "metric_signal": "tool_calls_per_task fell from 9 to 4 once rules were injected",
    "before": {"pass_at_1": 2 / 3, "pass_pow_k": 0.5},
    "after": {"pass_at_1": 5 / 6, "pass_pow_k": 0.75},
}


def test_extract_lesson_parses_a_well_formed_response(make_complete):
    complete, fake = make_complete(
        [
            json.dumps(
                {
                    "lever": "memory",
                    "trigger": "agent must map free-text input to a fixed label vocabulary",
                    "lesson": "Write one rule per label with the evidence case ids; inject "
                    "only rules whose keywords overlap the input.",
                    "domain_tags": ["Classification", "classification", "Triage"],
                }
            )
        ]
    )
    lesson, response = extract_lesson(FIX_CARD, complete=complete, model="cheap-model")

    assert lesson["lever"] == "memory"
    assert "label vocabulary" in lesson["trigger"]
    assert lesson["domain_tags"] == ["classification", "triage"]  # de-duplicated, lowercased
    assert fake.call_count == 1
    assert response["text"]


def test_extract_lesson_never_leaks_the_source_domain_into_the_prompt_instructions():
    """The system prompt itself must forbid domain-specific detail (rule §2 of
    the contract) regardless of what any one call returns."""
    from backend.playbook.extract import _SYSTEM_PROMPT

    assert "generaliz" in _SYSTEM_PROMPT.lower()
    assert "domain" in _SYSTEM_PROMPT.lower()


def test_extract_lesson_retries_once_on_unparseable_json(make_complete):
    complete, fake = make_complete(
        [
            "sure, here it is: not json",
            json.dumps(
                {
                    "lever": "tools",
                    "trigger": "an agent's tool call is rejected for an invalid parameter",
                    "lesson": "Rewrite the tool's error message to show a valid example call.",
                    "domain_tags": ["tool_use"],
                }
            ),
        ]
    )
    lesson, _response = extract_lesson(FIX_CARD, complete=complete, model="cheap-model")
    assert lesson["lever"] == "tools"
    assert fake.call_count == 2


def test_extract_lesson_raises_after_a_second_unusable_response(make_complete):
    complete, _fake = make_complete(["still not json", "nope, still not json"])
    with pytest.raises(LessonExtractionError):
        extract_lesson(FIX_CARD, complete=complete, model="cheap-model")


def test_extract_lesson_falls_back_to_the_fix_cards_own_lever_on_a_bad_enum(make_complete):
    complete, _fake = make_complete(
        [
            json.dumps(
                {
                    "lever": "not_a_real_lever",
                    "trigger": "agent must map free-text input to a fixed label vocabulary",
                    "lesson": "Write one rule per label.",
                    "domain_tags": [],
                }
            )
        ]
    )
    lesson, _response = extract_lesson(FIX_CARD, complete=complete, model="cheap-model")
    assert lesson["lever"] == "memory"  # FIX_CARD's own lever


def test_extract_lesson_rejects_an_empty_trigger_or_lesson(make_complete):
    complete, _fake = make_complete(
        [
            json.dumps({"lever": "memory", "trigger": "", "lesson": "", "domain_tags": []}),
            json.dumps({"lever": "memory", "trigger": "", "lesson": "", "domain_tags": []}),
        ]
    )
    with pytest.raises(LessonExtractionError):
        extract_lesson(FIX_CARD, complete=complete, model="cheap-model")
