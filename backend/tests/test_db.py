from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.db import applied_migrations, connect, db_path, init_db, migrate

EXPECTED_TABLES = {"events", "agents", "issues", "lessons", "improve_jobs", "schema_migrations"}


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_migrations_apply_on_a_fresh_db(db_file: Path):
    conn = init_db(db_file)
    try:
        assert EXPECTED_TABLES <= _tables(conn)
        assert applied_migrations(conn) == [1]
    finally:
        conn.close()


def test_migrations_are_idempotent(db_file: Path):
    conn = init_db(db_file)
    try:
        assert migrate(conn) == []  # already applied by init_db
        before = applied_migrations(conn)
        assert migrate(conn) == []
        assert applied_migrations(conn) == before
    finally:
        conn.close()


def test_events_table_matches_the_contract_ddl(conn):
    cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert set(cols) == {
        "id",
        "ts",
        "kind",
        "agent_id",
        "agent_version",
        "run_id",
        "lever",
        "payload",
    }
    assert cols["ts"]["notnull"] == 1
    assert cols["kind"]["notnull"] == 1
    assert cols["payload"]["notnull"] == 1
    # Nullable, per section 4.1.
    assert cols["agent_id"]["notnull"] == 0
    assert cols["lever"]["notnull"] == 0


def test_db_path_prefers_argument_then_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TO_DB_PATH", str(tmp_path / "from_env.sqlite3"))
    assert db_path(tmp_path / "explicit.sqlite3").name == "explicit.sqlite3"
    assert db_path().name == "from_env.sqlite3"
    monkeypatch.delenv("TO_DB_PATH")
    assert db_path() == Path(os.path.join(str(db_path().parent), "to.sqlite3"))


def test_connect_creates_the_parent_directory(tmp_path: Path):
    target = tmp_path / "nested" / "dir" / "to.sqlite3"
    conn = connect(target)
    conn.close()
    assert target.parent.is_dir()
