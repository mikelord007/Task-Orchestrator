"""The ledger read endpoints (``contracts/api.md`` / PLAN_ADDENDUM.md sec A).

The router is mounted on a bare app here so these tests do not depend on
``backend/app.py``; the connection dependency is overridden with the seeded
in-memory ledger.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ledger import api
from backend.tests.ledger import seed as seed_module
from backend.tests.ledger.seed import AGENT_ID, SeededLedger


def _client(conn: sqlite3.Connection, root: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("TASK_ORCHESTRATOR_ROOT", str(root))
    app = FastAPI()
    app.include_router(api.router)

    def override() -> Iterator[sqlite3.Connection]:
        yield conn

    app.dependency_overrides[api.get_connection] = override
    return TestClient(app)


@pytest.fixture
def client(seeded: SeededLedger, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _client(seeded.conn, seeded.root, monkeypatch)


@pytest.fixture
def empty_client(
    empty_ledger: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    return _client(empty_ledger, tmp_path, monkeypatch)


def test_get_events_filters_by_agent_and_kind(client: TestClient) -> None:
    body = client.get(
        "/events", params={"agent_id": AGENT_ID, "kind": "run_finished"}
    ).json()
    assert [e["run_id"] for e in body] == [
        "run_v0_train",
        "run_v0_holdout",
        "run_v1_train",
        "run_v1_holdout",
    ]
    assert body[0]["payload"]["split"] == "train"
    assert body[0]["payload"]["trials"] == 3


def test_get_events_since_is_inclusive_and_ordered(client: TestClient) -> None:
    everything = client.get("/events").json()
    assert [e["id"] for e in everything] == sorted(e["id"] for e in everything)

    midpoint = everything[len(everything) // 2]["ts"]
    later = client.get("/events", params={"since": midpoint}).json()
    assert later
    assert all(e["ts"] >= midpoint for e in later)


def test_get_events_on_an_empty_ledger_is_an_empty_list(
    empty_client: TestClient,
) -> None:
    assert empty_client.get("/events").json() == []


def test_get_insights(client: TestClient) -> None:
    body = client.get(f"/insights/{AGENT_ID}").json()
    assert body["trials"] == 3
    assert len(body["pass_at_1_by_version"]) == 4
    assert len(body["pass_pow_k_by_version"]) == 4
    assert body["pass_at_1_by_version"][0]["mean"] == pytest.approx(2 / 3)
    assert body["pass_pow_k_by_version"][0]["mean"] == pytest.approx(0.5)
    assert body["drift"]["count_by_kind"] == {"loop": 2, "budget": 1, "step_limit": 1}
    assert body["memory_by_version"][1]["mean_confidence"] == pytest.approx(0.7)
    assert body["tool_stats_by_version"][0]["calls"] == pytest.approx(9.0)
    assert body["graduated_count"] == 3
    assert body["saturated"] is False
    assert body["flagged_tasks"] == []


def test_insights_compare_is_not_shadowed_by_the_agent_id_route(
    client: TestClient,
) -> None:
    body = client.get("/insights/compare").json()
    assert set(body["by_domain"]) == {"github_triage", "ticket_triage"}
    assert body["ablation"] is None


def test_insights_compare_returns_the_ablation_report(
    seeded_with_ablation: SeededLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(seeded_with_ablation.conn, seeded_with_ablation.root, monkeypatch)
    body = client.get("/insights/compare").json()
    assert body["ablation"]["applied_lessons"] == ["l1"]


def test_get_fixes(client: TestClient) -> None:
    body = client.get(f"/agents/{AGENT_ID}/fixes").json()
    assert [c["to_version"] for c in body] == [2, 1]
    assert body[0]["status"] == "rejected"
    assert body[1]["status"] == "accepted"
    assert body[1]["diff_url"] == f"/agents/{AGENT_ID}/fixes/1/diff"
    assert body[1]["metric_signal"].startswith("tool_calls_per_task fell")


def test_get_fix_diff_is_plain_text(client: TestClient) -> None:
    response = client.get(f"/agents/{AGENT_ID}/fixes/1/diff")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "memory/rules.jsonl" in response.text


def test_get_fix_diff_404s_when_there_is_no_such_fix(client: TestClient) -> None:
    assert client.get(f"/agents/{AGENT_ID}/fixes/99/diff").status_code == 404


def test_get_compare(client: TestClient) -> None:
    body = client.get(f"/agents/{AGENT_ID}/compare", params={"case_id": "c4"}).json()
    assert body["expected"]["component"] == "pty"
    assert body["v0"]["output"]["component"] == "core"
    assert body["current"]["output"]["component"] == "pty"
    assert body["current"]["tool_calls"] == 4
    assert body["current"]["trial"] == 0


def test_get_compare_404s_for_an_unknown_agent(client: TestClient) -> None:
    assert (
        client.get("/agents/nope/compare", params={"case_id": "c4"}).status_code == 404
    )


def test_insights_on_an_empty_ledger_is_honest(empty_client: TestClient) -> None:
    body = empty_client.get("/insights/nobody").json()
    assert body["pass_at_1_by_version"] == []
    assert body["pass_pow_k_by_version"] == []
    assert body["trials"] is None
    assert body["drift"]["tokens_saved"] == 0
    assert body["graduated_count"] == 0
    assert body["saturated"] is False
    assert empty_client.get("/agents/nobody/fixes").json() == []


def test_the_seed_builder_is_reusable_for_mocks(tmp_path: Path) -> None:
    """W9 renders against this fixture; building it twice must not diverge."""
    first = sqlite3.connect(":memory:")
    second = sqlite3.connect(":memory:")
    try:
        a = seed_module.build(first, tmp_path / "a")
        b = seed_module.build(second, tmp_path / "b")
        rows_a = first.execute(
            "SELECT kind, payload FROM events ORDER BY id"
        ).fetchall()
        rows_b = second.execute(
            "SELECT kind, payload FROM events ORDER BY id"
        ).fetchall()
        assert rows_a == rows_b
        assert a.run_ids == b.run_ids
    finally:
        first.close()
        second.close()
