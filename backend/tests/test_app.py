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


def test_discover_routers_finds_a_dummy_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A subpackage exposing `api.router` is found without editing app.py."""
    import importlib
    import sys

    from backend.app import discover_routers

    pkg_dir = tmp_path / "demo_pkg"
    sub_dir = pkg_dir / "sub"
    sub_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (sub_dir / "__init__.py").write_text("", encoding="utf-8")
    (sub_dir / "api.py").write_text(
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n\n"
        "@router.get('/dummy')\n"
        "def dummy():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    demo_pkg = importlib.import_module("demo_pkg")
    try:
        routers = discover_routers(demo_pkg)
        assert len(routers) == 1
        assert any(getattr(r, "path", "") == "/dummy" for r in routers[0].routes)
    finally:
        for name in list(sys.modules):
            if name == "demo_pkg" or name.startswith("demo_pkg."):
                del sys.modules[name]


def test_discover_routers_skips_subpackages_with_no_api_module():
    from fastapi import APIRouter

    import backend
    from backend.app import discover_routers

    # backend.tests, backend.testing etc. have no api.py and must not raise or
    # contribute a router - unlike backend.runtime, which by now does (W2).
    routers = discover_routers(backend)
    assert all(isinstance(r, APIRouter) for r in routers)
