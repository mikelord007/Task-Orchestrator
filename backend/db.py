"""SQLite connection + numbered migrations (PLAN.md section 5).

Migration files live in `backend/migrations/NNNN_<name>.sql` and are applied in
numeric order inside one transaction each, then recorded in `schema_migrations`.
**A migration is never edited after it merges** -- add a new numbered file.

The database path comes from `TO_DB_PATH`, defaulting to `runs/to.sqlite3` at
the repo root. Tests pass an explicit temp path.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "MIGRATIONS_DIR",
    "db_path",
    "connect",
    "migrate",
    "init_db",
    "applied_migrations",
    "utcnow",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DEFAULT_DB_PATH = REPO_ROOT / "runs" / "to.sqlite3"

_MIGRATION_RE = re.compile(r"^(\d+)_.+\.sql$")


def utcnow() -> str:
    """ISO8601 UTC timestamp, the only timestamp format used in the ledger."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def db_path(path: str | Path | None = None) -> Path:
    """Resolve the database path: explicit arg > `TO_DB_PATH` > `runs/to.sqlite3`."""
    if path is not None:
        return Path(path)
    env = os.environ.get("TO_DB_PATH")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def connect(
    path: str | Path | None = None, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enabled.

    The parent directory is created if needed; the schema is *not* applied here
    (call `init_db` for that). Connections remain thread-affine unless a caller
    explicitly opts out for a controlled, sequential cross-thread handoff.
    """
    resolved = db_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _discover_migrations() -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for sql in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_RE.match(sql.name)
        if match is None:
            raise ValueError(f"migration {sql.name!r} must be named NNNN_<name>.sql")
        found.append((int(match.group(1)), sql.name, sql))
    found.sort(key=lambda item: item[0])
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration numbers: {versions}")
    return found


def _strip_sql_comments(sql: str) -> str:
    """Drop `-- ...` line comments. Our migrations never put `--` inside a
    string literal, so this line-based strip is sufficient (a full SQL
    tokenizer would be overkill for hand-written DDL)."""
    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        lines.append(line if idx == -1 else line[:idx])
    return "\n".join(lines)


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements for `execute()`.

    `executescript()` cannot be used here: it implicitly commits any pending
    transaction before running and does not participate in an explicit
    transaction, so a script that fails partway leaves earlier `CREATE TABLE`
    statements committed with no matching `schema_migrations` row -- the next
    run then dies on "table already exists". Splitting and running each
    statement inside one explicit transaction makes a migration atomic.
    """
    cleaned = _strip_sql_comments(sql)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          applied_ts TEXT NOT NULL
        )
        """
    )


def applied_migrations(conn: sqlite3.Connection) -> list[int]:
    """Migration versions already recorded in this database, ascending."""
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every pending migration in order. Returns the names applied.

    Idempotent: running it again on the same database applies nothing. Each
    migration's statements plus its `schema_migrations` row commit in one
    atomic transaction -- a failure partway rolls back the whole migration, so
    a retry never finds a half-applied schema (see `_split_statements`).
    """
    _ensure_migrations_table(conn)
    already = set(applied_migrations(conn))
    applied: list[str] = []
    for version, name, sql_path in _discover_migrations():
        if version in already:
            continue
        statements = _split_statements(sql_path.read_text(encoding="utf-8"))
        conn.execute("BEGIN")
        try:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_ts) VALUES (?, ?, ?)",
                (version, name, utcnow()),
            )
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        applied.append(name)
    return applied


def init_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection and bring its schema up to date."""
    conn = connect(path)
    migrate(conn)
    return conn
