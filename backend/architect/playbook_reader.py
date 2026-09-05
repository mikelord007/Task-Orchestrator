"""Read and rank playbook lessons for one generation (step 6, use_playbook only)."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = "playbook/lessons.jsonl"
DEFAULT_LIMIT = 8


def read_lessons(path: str | Path = DEFAULT_PATH) -> list[dict]:
    """All lessons in the playbook, or ``[]`` if it does not exist yet."""
    lessons_path = Path(path)
    if not lessons_path.is_file():
        return []
    lessons = []
    with lessons_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                lessons.append(json.loads(line))
    return lessons


def select_relevant_lessons(
    lessons: list[dict], domain: str, goal: str, limit: int = DEFAULT_LIMIT
) -> list[dict]:
    """Keyword-overlap ranking against ``domain_tags`` -- no embeddings, matching §0.2's memory injection."""
    keywords = {word.lower() for word in f"{domain} {goal}".split() if len(word) > 2}

    def overlap(lesson: dict) -> int:
        tags = lesson.get("domain_tags") or []
        return sum(1 for tag in tags if str(tag).lower() in keywords)

    ranked = sorted(lessons, key=overlap, reverse=True)
    matched = [lesson for lesson in ranked if overlap(lesson) > 0]
    unmatched = [lesson for lesson in ranked if overlap(lesson) == 0]
    return (matched + unmatched)[:limit]
