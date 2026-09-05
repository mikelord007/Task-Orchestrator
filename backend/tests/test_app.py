from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def client(db_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TO_DB_PATH", str(db_file))
    with TestClient(create_app()) as c:
        yield c


def test_healthz(client: TestClient, db_file: Path):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": str(db_file)}


def test_startup_migrates_the_database(client: TestClient, db_file: Path):
    from backend.db import applied_migrations, connect

    client.get("/healthz")
    conn = connect(db_file)
    try:
        assert applied_migrations(conn) == [1]
    finally:
        conn.close()
