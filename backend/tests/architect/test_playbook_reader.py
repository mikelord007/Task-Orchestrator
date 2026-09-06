from __future__ import annotations

import json

from backend.architect.playbook_reader import read_lessons, select_relevant_lessons


def test_read_lessons_returns_empty_list_when_the_file_does_not_exist(tmp_path):
    assert read_lessons(tmp_path / "nope.jsonl") == []


def test_read_lessons_parses_each_line(tmp_path):
    path = tmp_path / "lessons.jsonl"
    path.write_text(
        '{"id": "l1", "lever": "prompt", "lesson": "x", "domain_tags": ["github"]}\n'
        '{"id": "l2", "lever": "tools", "lesson": "y", "domain_tags": ["ticket"]}\n',
        encoding="utf-8",
    )
    lessons = read_lessons(path)
    assert [lesson["id"] for lesson in lessons] == ["l1", "l2"]


def test_select_relevant_lessons_ranks_by_tag_overlap_then_fills_with_the_rest():
    lessons = [
        {"id": "l1", "domain_tags": ["ticket_triage"]},
        {"id": "l2", "domain_tags": ["github", "triage"]},
        {"id": "l3", "domain_tags": []},
    ]
    selected = select_relevant_lessons(lessons, domain="github_triage", goal="triage github issues")
    ids = [lesson["id"] for lesson in selected]
    assert ids[0] == "l2"  # matches both "github" and "triage"
    assert set(ids) == {"l1", "l2", "l3"}  # nothing is dropped, just reordered


def test_select_relevant_lessons_respects_the_limit():
    lessons = [{"id": f"l{i}", "domain_tags": []} for i in range(20)]
    assert len(select_relevant_lessons(lessons, "d", "g", limit=3)) == 3


def test_lessons_survive_a_json_round_trip(tmp_path):
    path = tmp_path / "lessons.jsonl"
    entry = {"id": "l1", "lever": "memory", "lesson": "note", "domain_tags": ["x"]}
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert read_lessons(path) == [entry]
