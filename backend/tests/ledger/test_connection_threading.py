"""Regression coverage for the ledger API's real SQLite dependency."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend import db
from backend.ledger import api


@pytest.mark.anyio
async def test_real_connection_dependency_survives_concurrent_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sync dependency setup and endpoint work may use different pool threads."""
    database_path = tmp_path / "ledger.sqlite3"
    conn = db.init_db(database_path)
    conn.close()
    monkeypatch.setenv("TO_DB_PATH", str(database_path))

    app = FastAPI()
    app.include_router(api.router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(*(client.get("/events") for _ in range(100)))

    assert all(response.status_code == 200 for response in responses), [
        (response.status_code, response.text)
        for response in responses
        if response.status_code != 200
    ]
