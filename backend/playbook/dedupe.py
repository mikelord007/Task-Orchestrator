"""Near-duplicate detection for playbook lessons.

Rule §7 of the W8 brief: skip a lesson whose normalized ``trigger`` + ``lesson``
text is >= 0.85 similar (difflib ratio) to an existing one. No embeddings.
"""

from __future__ import annotations

import difflib
import re

SIMILARITY_THRESHOLD = 0.85

__all__ = ["SIMILARITY_THRESHOLD", "normalize", "similarity", "find_near_duplicate"]


def normalize(text: str) -> str:
    """Lowercase, whitespace-collapsed text for a similarity comparison."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _key(lesson: dict) -> str:
    return normalize(f"{lesson.get('trigger', '')} {lesson.get('lesson', '')}")


def similarity(a: dict, b: dict) -> float:
    """``difflib.SequenceMatcher`` ratio between two lessons' normalized text."""
    return difflib.SequenceMatcher(None, _key(a), _key(b)).ratio()


def find_near_duplicate(
    candidate: dict, existing: list[dict], *, threshold: float = SIMILARITY_THRESHOLD
) -> dict | None:
    """The first existing lesson at or above ``threshold`` similarity, or ``None``."""
    for lesson in existing:
        if similarity(candidate, lesson) >= threshold:
            return lesson
    return None
