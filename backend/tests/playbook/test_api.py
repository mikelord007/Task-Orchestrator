from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def client(db_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TO_DB_PATH", str(db_file))
    monkeypatch.setenv("TO_PLAYBOOK_PATH", str(tmp_path / "playbook" / "lessons.jsonl"))
    with TestClient(create_app()) as c:
        yield c


def test_get_playbook_is_empty_when_no_lessons_exist_yet(client: TestClient):
    response = client.get("/playbook")
    assert response.status_code == 200
    assert response.json() == []


def test_get_playbook_returns_lessons_parsed_as_is(client: TestClient, tmp_path: Path):
    path = tmp_path / "playbook" / "lessons.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lesson = {
        "id": "lesson_1",
        "lever": "memory",
        "trigger": "agent must map free-text input to a fixed label vocabulary",
        "lesson": "Write one rule per label.",
        "domain_tags": ["classification"],
        "source_agent_id": "a_1",
        "source_issue_id": None,
        "ts": "2026-09-06T11:20:00Z",
    }
    path.write_text(json.dumps(lesson) + "\n", encoding="utf-8")

    response = client.get("/playbook")
    assert response.status_code == 200
    assert response.json() == [lesson]
