from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.db import init_db
from backend.ledger.emit import emit
from backend.testing.fake_llm import FakeLLM
from backend.testing.fake_llm import text as llm_text


@pytest.fixture
def client(db_file: Path, evaluator_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TO_DB_PATH", str(db_file))
    monkeypatch.setenv("TO_AGENTS_ROOT", str(tmp_path / "agents"))
    monkeypatch.setenv("TO_EVALUATORS_ROOT", str(evaluator_dir))
    monkeypatch.setenv("TO_PLAYBOOK_PATH", str(tmp_path / "playbook" / "lessons.jsonl"))
    with TestClient(create_app()) as c:
        yield c


def _script_responses(responses: list[str]) -> FakeLLM:
    from backend import llm as backend_llm

    fake = FakeLLM([llm_text(r) for r in responses])
    backend_llm.set_client(fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_llm_client():
    yield
    from backend import llm as backend_llm

    backend_llm.reset_client()


def _create_body(**overrides) -> dict:
    body = {
        "goal": "triage widget issues",
        "domain": "widget_triage",
        "tools": ["json_validate", "date_parse"],
        "evaluator_id": "widget_triage",
        "use_playbook": False,
    }
    body.update(overrides)
    return body


def _script() -> list[str]:
    return [
        json.dumps({"mode": "single", "reason": "One call suffices."}),
        "Answer with a JSON object with keys: labels, component.",
        json.dumps({"tools": ["json_validate", "date_parse"], "glue_tool": None}),
    ]


def test_post_agents_creates_a_valid_package(client: TestClient):
    _script_responses(_script())
    response = client.post("/agents", json=_create_body())
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 0
    assert body["agent_id"].startswith("widget-triage-")


def test_post_agents_then_get_agent_returns_row_and_package(client: TestClient):
    _script_responses(_script())
    agent_id = client.post("/agents", json=_create_body()).json()["agent_id"]

    response = client.get(f"/agents/{agent_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == agent_id
    assert body["goal"] == "triage widget issues"
    assert body["current_version"] == 0
    assert body["agent_yaml"]["orchestration"] == "single"
    assert body["agent_yaml"]["orchestration_reason"] == "One call suffices."
    assert {tool["name"] for tool in body["tools"]} == {"json_validate", "date_parse"}
    assert all(tool["description"] for tool in body["tools"])
    assert body["memory"] == {"rules": [], "tool_notes": [], "episodes": []}
    assert "# Answer with" in body["prompt"] or "Answer with" in body["prompt"]


def test_get_agent_unknown_id_is_404(client: TestClient):
    response = client.get("/agents/does-not-exist")
    assert response.status_code == 404


def test_get_agents_lists_newest_first(client: TestClient):
    _script_responses(_script() * 2)
    first = client.post("/agents", json=_create_body()).json()["agent_id"]
    second = client.post("/agents", json=_create_body()).json()["agent_id"]

    response = client.get("/agents")
    assert response.status_code == 200
    ids = [row["agent_id"] for row in response.json()]
    assert ids[:2] == [second, first]


def test_get_agents_includes_frontend_summary_fields(client: TestClient):
    _script_responses(_script())
    agent_id = client.post("/agents", json=_create_body()).json()["agent_id"]

    row = client.get("/agents").json()[0]

    assert row["agent_id"] == agent_id
    assert row["name"] == "triage widget issues"
    assert row["latest_train"] is None
    assert row["latest_holdout"] is None


def test_get_agents_includes_latest_current_version_pass_stats(client: TestClient, db_file: Path):
    _script_responses(_script())
    agent_id = client.post("/agents", json=_create_body()).json()["agent_id"]
    conn = init_db(db_file)
    try:
        emit(
            "run_started",
            agent_id=agent_id,
            agent_version=0,
            run_id="train-run",
            split="train",
            case_count=1,
            trials=2,
            conn=conn,
        )
        for trial, passed in enumerate((True, False)):
            emit(
                "case_result",
                agent_id=agent_id,
                agent_version=0,
                run_id="train-run",
                case_id="c1",
                trial=trial,
                passed=passed,
                score=float(passed),
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.01,
                latency_ms=100,
                steps=1,
                transcript_path=f"runs/train-run/c1.t{trial}.json",
                tool_calls=0,
                tool_errors=0,
                conn=conn,
            )
        emit(
            "run_finished",
            agent_id=agent_id,
            agent_version=0,
            run_id="train-run",
            split="train",
            trials=2,
            pass_at_1=0.5,
            pass_pow_k=0.0,
            pass_rate_std=0.5,
            pass_rate_min=0.0,
            pass_rate_max=1.0,
            total_cost_usd=0.02,
            p50_latency_ms=100,
            p95_latency_ms=100,
            drift_count=0,
            tokens_saved_by_drift=0,
            conn=conn,
        )
    finally:
        conn.close()

    row = client.get("/agents").json()[0]
    assert row["latest_train"] == {
        "mean": 0.5,
        "std": 0.5,
        "min": 0.0,
        "max": 1.0,
        "trials": 2,
        "task_count": 1,
    }
    assert row["latest_holdout"] is None


def test_get_agent_version_reports_no_changes_diff_for_v0(client: TestClient):
    _script_responses(_script())
    agent_id = client.post("/agents", json=_create_body()).json()["agent_id"]

    response = client.get(f"/agents/{agent_id}/versions/0")
    assert response.status_code == 200
    assert response.json()["changes_diff"] is None


def test_get_agent_version_missing_is_404(client: TestClient):
    _script_responses(_script())
    agent_id = client.post("/agents", json=_create_body()).json()["agent_id"]

    response = client.get(f"/agents/{agent_id}/versions/7")
    assert response.status_code == 404


def test_get_evaluators_lists_the_synthetic_fixture(client: TestClient):
    response = client.get("/evaluators")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["evaluator_id"] == "widget_triage"
    assert body[0]["domain"] == "widget_triage"
    assert "Given an issue" in body[0]["description"]
    assert body[0]["case_counts"] == {"train": 2, "holdout": 1}


def test_post_agents_unknown_evaluator_is_404(client: TestClient):
    _script_responses(_script())
    response = client.post("/agents", json=_create_body(evaluator_id="does_not_exist"))
    assert response.status_code == 404


def test_post_agents_unknown_tools_is_422(client: TestClient):
    _script_responses(_script())
    response = client.post("/agents", json=_create_body(tools=["not_a_real_tool"]))
    assert response.status_code == 422
