from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    """A fresh SQLite file per test. Never the real runs/to.sqlite3."""
    return tmp_path / "to.sqlite3"


@pytest.fixture
def conn(db_file: Path):
    from backend.db import init_db

    connection = init_db(db_file)
    yield connection
    connection.close()
