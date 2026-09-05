"""The metrics layer must never write.

PLAN_ADDENDUM.md sec 0 / sec A: the ledger is append-only and display status is
*derived*, never stored. If any metric ever caches a result into a table,
these tests fail.
"""

from __future__ import annotations

import sqlite3

from backend.ledger import metrics
from backend.tests.ledger.seed import AGENT_ID, SeededLedger


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    ]


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in _table_names(conn)
    }


def _call_every_metric(seeded: SeededLedger) -> None:
    conn, root = seeded.conn, seeded.root
    metrics.pass_at_1(conn, AGENT_ID, 0, "train")
    metrics.pass_at_1(conn, AGENT_ID, 1, "holdout")
    metrics.pass_pow_k(conn, AGENT_ID, 0, "train")
    metrics.pass_pow_k(conn, AGENT_ID, 1, "holdout")
    metrics.stable_pass_set(conn, AGENT_ID, 0)
    metrics.cost_per_run(conn, AGENT_ID, 0, "train")
    metrics.latency_percentiles(conn, AGENT_ID, 0, "train")
    metrics.fixes_by_lever(conn, AGENT_ID)
    metrics.regressions_caught(conn, AGENT_ID)
    metrics.issue_stats(conn, AGENT_ID)
    metrics.lessons_count(conn)
    metrics.drift_stats(conn, AGENT_ID)
    metrics.series_by_version(conn, AGENT_ID)
    metrics.markers(conn, AGENT_ID)
    metrics.graduated_count(conn, AGENT_ID)
    metrics.saturated(conn, AGENT_ID)
    metrics.zero_pass_tasks(conn, AGENT_ID)
    metrics.rule_stats(conn, AGENT_ID)
    metrics.memory_by_version(conn, AGENT_ID, root)
    metrics.tool_call_stats(conn, AGENT_ID, 0, "train", root)
    metrics.tool_stats_by_version(conn, AGENT_ID, root)
    metrics.fix_cards(conn, AGENT_ID)
    metrics.fix_diff(conn, AGENT_ID, 1, root)
    metrics.compare(conn, AGENT_ID, "c4", root)
    metrics.insights(conn, AGENT_ID, root)
    metrics.insights_compare(conn, root)


def test_no_metric_changes_any_row(seeded: SeededLedger) -> None:
    before_tables = _table_names(seeded.conn)
    before_counts = _row_counts(seeded.conn)
    before_changes = seeded.conn.total_changes

    _call_every_metric(seeded)

    assert _table_names(seeded.conn) == before_tables
    assert _row_counts(seeded.conn) == before_counts
    assert seeded.conn.total_changes == before_changes


def test_metrics_are_stable_under_repetition(seeded: SeededLedger) -> None:
    """Same ledger in, same numbers out -- no hidden state between calls."""
    first = metrics.insights(seeded.conn, AGENT_ID, seeded.root)
    _call_every_metric(seeded)
    second = metrics.insights(seeded.conn, AGENT_ID, seeded.root)
    assert first == second


def test_metrics_work_on_a_read_only_connection(seeded: SeededLedger, tmp_path) -> None:
    """A connection opened read-only proves purity at the driver level."""
    db_path = tmp_path / "ledger.sqlite3"
    disk = sqlite3.connect(db_path)
    seeded.conn.backup(disk)
    disk.close()

    read_only = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        payload = metrics.insights(read_only, AGENT_ID, seeded.root)
    finally:
        read_only.close()
    assert payload["regressions_caught"] == 1
