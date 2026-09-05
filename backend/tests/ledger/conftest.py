"""Fixtures for the ledger tests."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# Make ``backend.*`` importable however pytest was invoked. Done before the
# fixtures import ``seed``, which is why that import is function-local.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _seed_module():
    from backend.tests.ledger import seed

    return seed


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    # check_same_thread=False: TestClient runs handlers on a worker thread.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def empty_ledger(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Schema only -- no events, no agents. The honest-empty-state fixture."""
    _seed_module().create_schema(conn)
    return conn


@pytest.fixture
def seeded(conn: sqlite3.Connection, tmp_path: Path):
    """The full scenario: two versions, drift, fixes, memory, issues, lessons."""
    return _seed_module().build(conn, tmp_path)


@pytest.fixture
def seeded_with_ablation(conn: sqlite3.Connection, tmp_path: Path):
    return _seed_module().build(conn, tmp_path, ablation=True)
