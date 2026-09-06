from __future__ import annotations

from backend.playbook.dedupe import find_near_duplicate, normalize, similarity


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  Map   Paths\nTo Components  ") == "map paths to components"


def test_identical_lessons_are_maximally_similar():
    lesson = {"trigger": "free text to fixed vocabulary", "lesson": "write one rule per label"}
    assert similarity(lesson, lesson) == 1.0


def test_find_near_duplicate_matches_reworded_text_above_threshold():
    existing = [
        {
            "id": "l1",
            "trigger": "agent must map free-text reports to a fixed label vocabulary",
            "lesson": "write one rule per label describing the signal that selects it",
        }
    ]
    candidate = {
        "trigger": "agent must map free text reports to a fixed label vocabulary",
        "lesson": "write one rule per label describing the signal that selects it",
    }
    duplicate = find_near_duplicate(candidate, existing)
    assert duplicate is not None
    assert duplicate["id"] == "l1"


def test_find_near_duplicate_returns_none_for_a_genuinely_different_lesson():
    existing = [
        {
            "trigger": "agent must map free-text reports to a fixed label vocabulary",
            "lesson": "write one rule per label describing the signal that selects it",
        }
    ]
    candidate = {
        "trigger": "agent calls the same tool with identical arguments repeatedly",
        "lesson": "cap retries and nudge the agent to change approach",
    }
    assert find_near_duplicate(candidate, existing) is None


def test_find_near_duplicate_respects_a_custom_threshold():
    existing = [{"trigger": "abc", "lesson": "def"}]
    candidate = {"trigger": "abd", "lesson": "def"}
    assert find_near_duplicate(candidate, existing, threshold=0.99) is None
    assert find_near_duplicate(candidate, existing, threshold=0.5) is not None
