"""`POST /agents/{id}/improve` (`contracts/api.md`). No network, no LLM.

Improving is minutes of work, so the endpoint is async by the API's own
convention: it validates, hands the job to W2's `jobs.py` helper, and returns
`{job_id}` immediately. `improve` itself is exercised in `test_improve.py`;
here it is replaced by a stub, because what is under test is the handler --
the 404, the job record, the progress plumbing and the stored payload.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.improver import api as improver_api
from backend.improver.improve import AttemptOutcome, ImproveResult
from backend.runtime.jobs import STATUS_DONE, STATUS_ERROR, JobStore

AGENT_ID = "toy"

RESULT = ImproveResult(
    agent_id=AGENT_ID,
    starting_version=0,
    current_version=1,
    attempts=[
        AttemptOutcome(
            attempt=1,
            from_version=0,
            candidate_version=1,
            lever="memory",
            failing_group_signature="wrong_output",
            accepted=True,
        )
    ],
)


@pytest.fixture
def api_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A file-backed ledger at `TO_DB_PATH` with one agent on record.

    The handler resolves the agent through `backend.db.init_db()`'s default
    connection (it has no injection point), so the environment variable is
    the seam.
    """
    from backend.db import init_db

    path = tmp_path / "to.sqlite3"
    monkeypatch.setenv("TO_DB_PATH", str(path))
    conn = init_db(path)
    conn.execute(
        "INSERT INTO agents (agent_id, goal, domain, evaluator_id, current_version, created_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (AGENT_ID, "Triage toy tickets", "toy", "toy_evaluator", 0, "2026-09-06T11:59:00Z"),
    )
    conn.commit()
    conn.close()
    yield path


@pytest.fixture
def store(api_db: Path) -> JobStore:
    from backend.runtime.jobs import default_connection_factory

    return JobStore(default_connection_factory(api_db))


@pytest.fixture
def client(api_db: Path) -> TestClient:
    app = FastAPI()
    app.include_router(improver_api.router)
    return TestClient(app)


def await_job(store: JobStore, job_id: str, timeout: float = 5.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job is not None and job.status in {STATUS_DONE, STATUS_ERROR}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# -- the route ----------------------------------------------------------


def test_post_improve_returns_a_job_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(improver_api, "improve", lambda *a, **k: RESULT)

    response = client.post(f"/agents/{AGENT_ID}/improve", json={"max_attempts": 2})

    assert response.status_code == 200
    assert set(response.json()) == {"job_id"}
    assert response.json()["job_id"].startswith("job_")


def test_post_improve_defaults_max_attempts_to_three(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(agent_id: str, **kwargs: Any) -> ImproveResult:
        seen.update({"agent_id": agent_id, **kwargs})
        return RESULT

    monkeypatch.setattr(improver_api, "improve", fake)
    assert client.post(f"/agents/{AGENT_ID}/improve", json={}).status_code == 200

    deadline = time.monotonic() + 5.0
    while "agent_id" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen["agent_id"] == AGENT_ID
    assert seen["max_attempts"] == 3
    assert seen["issue_id"] is None


def test_an_unknown_agent_is_a_404(client: TestClient) -> None:
    response = client.post("/agents/nope/improve", json={})
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_the_issue_id_is_passed_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(agent_id: str, **kwargs: Any) -> ImproveResult:
        seen.update(kwargs)
        return RESULT

    monkeypatch.setattr(improver_api, "improve", fake)
    client.post(f"/agents/{AGENT_ID}/improve", json={"issue_id": "iss_4"})

    deadline = time.monotonic() + 5.0
    while "issue_id" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen["issue_id"] == "iss_4"


# -- the job ------------------------------------------------------------


def test_the_job_stores_the_improve_result_payload(
    store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(improver_api, "improve", lambda *a, **k: RESULT)

    job_id = improver_api.start_improve(AGENT_ID, store=store)
    job = await_job(store, job_id)

    assert job.status == STATUS_DONE
    assert job.result == RESULT.payload()
    assert job.result["improved"] is True
    assert job.result["attempts"][0]["lever"] == "memory"


def test_progress_is_reported_per_attempt(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(agent_id: str, *, progress: Any = None, **kwargs: Any) -> ImproveResult:
        progress(1, 3)
        progress(2, 3)
        return RESULT

    monkeypatch.setattr(improver_api, "improve", fake)
    job = await_job(store, improver_api.start_improve(AGENT_ID, store=store))

    assert job.status == STATUS_DONE
    assert job.progress() == {"done": 2, "total": 3}


def test_a_failing_improve_is_a_failed_job_not_a_500(
    store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request already returned `{job_id}`; a later failure has to be
    reported on the job, which is the only thing the caller can still read."""

    def boom(*_args: Any, **_kwargs: Any) -> ImproveResult:
        raise RuntimeError("the candidate package would not load")

    monkeypatch.setattr(improver_api, "improve", boom)
    job = await_job(store, improver_api.start_improve(AGENT_ID, store=store))

    assert job.status == STATUS_ERROR
    assert "the candidate package would not load" in job.error


def test_start_improve_rejects_an_unknown_agent_before_creating_a_job(
    store: JobStore,
) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        improver_api.start_improve("nope", store=store)
    assert excinfo.value.status_code == 404


def test_the_router_is_discovered_by_the_app() -> None:
    """`backend/app.py` auto-registers `<package>.api.router`, so the
    improver endpoint needs no edit to `app.py` to be mounted."""
    import backend
    from backend.app import discover_routers

    routes = {
        route.path
        for router in discover_routers(backend)
        for route in router.routes
        if hasattr(route, "path")
    }
    assert "/agents/{agent_id}/improve" in routes
