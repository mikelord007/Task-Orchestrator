from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.demo_limits import (
    DemoLimitExceeded,
    claim_workflow_slot,
    consume_action,
    ensure_token_budget,
    hash_client,
    record_usage,
    release_token_reservation,
    reserve_token_budget,
)


@pytest.fixture
def limited_demo(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TO_DB_PATH", str(tmp_path / "demo.sqlite3"))
    monkeypatch.setenv("API_AUTH_TOKEN", "test-bearer")
    monkeypatch.setenv("REQUIRE_API_AUTH", "true")
    monkeypatch.setenv("PUBLIC_DEMO_LIMITS", "1")
    monkeypatch.setenv("DEMO_DAILY_ACTION_LIMIT", "3")
    monkeypatch.setenv("DEMO_CLIENT_HOURLY_LIMIT", "2")
    monkeypatch.setenv("DEMO_CLIENT_COOLDOWN_S", "60")
    monkeypatch.setenv("DEMO_DAILY_TOKEN_LIMIT", "100")
    monkeypatch.setenv("LLM_MAX_TOKENS", "20")


def test_client_address_is_hashed_and_rate_limited(limited_demo):
    digest = hash_client("203.0.113.4")
    assert digest != "203.0.113.4"
    assert len(digest) == 64

    consume_action("create", "203.0.113.4")
    with pytest.raises(DemoLimitExceeded, match="cooldown"):
        consume_action("run", "203.0.113.4")


def test_global_daily_action_limit_is_persistent(limited_demo, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_CLIENT_COOLDOWN_S", "0")
    consume_action("create", "203.0.113.1")
    consume_action("run", "203.0.113.2")
    consume_action("improve", "203.0.113.3")
    with pytest.raises(DemoLimitExceeded, match="daily"):
        consume_action("create", "203.0.113.4")


def test_daily_token_budget_is_persistent(limited_demo):
    record_usage("demo-model", 60, 40)
    with pytest.raises(DemoLimitExceeded, match="token"):
        ensure_token_budget()


def test_token_reservations_atomically_hold_daily_capacity(limited_demo):
    first = reserve_token_budget(60)
    try:
        with pytest.raises(DemoLimitExceeded, match="token"):
            reserve_token_budget(50)
    finally:
        release_token_reservation(first)

    second = reserve_token_budget(50)
    release_token_reservation(second)


def test_recorded_usage_reconciles_its_reservation(limited_demo):
    reservation_id = reserve_token_budget(100)
    record_usage("demo-model", 60, 40, reservation_id=reservation_id)

    with pytest.raises(DemoLimitExceeded, match="token"):
        ensure_token_budget()


def test_workflow_concurrency_rejects_instead_of_queueing(limited_demo):
    first = claim_workflow_slot()
    try:
        with pytest.raises(DemoLimitExceeded, match="workflow"):
            claim_workflow_slot()
    finally:
        first.release()

    second = claim_workflow_slot()
    second.release()


def test_http_model_action_limit_returns_429(limited_demo, monkeypatch: pytest.MonkeyPatch):
    from backend.app import create_app

    monkeypatch.setenv("DEMO_CLIENT_COOLDOWN_S", "60")
    headers = {"Authorization": "Bearer test-bearer", "X-Demo-Client-IP": "203.0.113.9"}
    with TestClient(create_app()) as client:
        # Invalid input is rejected by validation, but is still a paid-route
        # attempt and consumes the cooldown before any provider call.
        assert client.post("/agents", json={}, headers=headers).status_code == 422
        limited = client.post("/agents", json={}, headers=headers)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_background_workflow_slot_is_released(tmp_path, limited_demo):
    from backend.runtime.jobs import JobStore, default_connection_factory, run_in_background

    store = JobStore(default_connection_factory(tmp_path / "jobs.sqlite3"))
    release = threading.Event()

    def work(_progress):
        release.wait(timeout=2)
        return {"ok": True}

    run_in_background(store, "run", "a1", work)
    with pytest.raises(DemoLimitExceeded):
        run_in_background(store, "run", "a2", work)
    release.set()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            slot = claim_workflow_slot()
        except DemoLimitExceeded:
            time.sleep(0.01)
            continue
        slot.release()
        break
    else:
        raise AssertionError("background workflow slot was not released")
