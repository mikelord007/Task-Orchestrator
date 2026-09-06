"""An empty ledger reports empty -- never a zero standing in for data.

PLAN.md 2.4 / PLAN_ADDENDUM.md sec 0: no fabricated numbers anywhere; an empty
ledger yields an honest empty state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ledger import metrics

_EMPTY_PASS_STAT = {
    "mean": None,
    "std": None,
    "min": None,
    "max": None,
    "trials": None,
    "task_count": 0,
}


def test_pass_at_1_is_null_not_zero(empty_ledger: sqlite3.Connection) -> None:
    assert metrics.pass_at_1(empty_ledger, "nobody", 0, "train") == _EMPTY_PASS_STAT


def test_pass_pow_k_is_null_not_zero(empty_ledger: sqlite3.Connection) -> None:
    assert metrics.pass_pow_k(empty_ledger, "nobody", 0, "train") == _EMPTY_PASS_STAT


def test_scalar_metrics_are_null_or_empty(empty_ledger: sqlite3.Connection) -> None:
    assert metrics.stable_pass_set(empty_ledger, "nobody", 0) == set()
    assert metrics.cost_per_run(empty_ledger, "nobody", 0, "train") is None
    assert metrics.latency_percentiles(empty_ledger, "nobody", 0, "train") == {
        "p50": None,
        "p95": None,
    }
    assert metrics.fixes_by_lever(empty_ledger, "nobody") == {}
    assert metrics.regressions_caught(empty_ledger, "nobody") == 0
    assert metrics.issue_stats(empty_ledger, "nobody") == {"open": 0, "closed": 0}
    assert metrics.lessons_count(empty_ledger) == 0
    assert metrics.fix_cards(empty_ledger, "nobody") == []
    assert metrics.markers(empty_ledger, "nobody") == []
    assert metrics.rule_stats(empty_ledger, "nobody") == {}
    assert metrics.graduated_count(empty_ledger, "nobody") == 0
    assert metrics.saturated(empty_ledger, "nobody") is False
    assert metrics.zero_pass_tasks(empty_ledger, "nobody") == []


def test_drift_stats_are_empty(empty_ledger: sqlite3.Connection) -> None:
    assert metrics.drift_stats(empty_ledger, "nobody") == {
        "count_by_kind": {},
        "tokens_saved": 0,
        "cases_recovered_by_nudge": 0,
        "count_by_version": {},
    }


def test_series_are_empty_lists(empty_ledger: sqlite3.Connection) -> None:
    assert metrics.series_by_version(empty_ledger, "nobody") == {
        "pass_at_1_by_version": [],
        "pass_pow_k_by_version": [],
        "cost_by_version": [],
        "latency_by_version": [],
    }


def test_tool_call_stats_is_empty(empty_ledger: sqlite3.Connection, tmp_path: Path) -> None:
    assert metrics.tool_call_stats(empty_ledger, "nobody", 0, "train", tmp_path) == {
        "tasks": {},
        "aggregate": {
            "calls": None,
            "errors": None,
            "redundant": None,
            "tool_tokens": None,
            "latency_ms": None,
            "tool_tokens_estimated": None,
        },
    }
    assert metrics.tool_stats_by_version(empty_ledger, "nobody", tmp_path) == []


def test_memory_by_version_is_empty(empty_ledger: sqlite3.Connection, tmp_path: Path) -> None:
    assert metrics.memory_by_version(empty_ledger, "nobody", tmp_path) == []


def test_insights_is_a_complete_but_empty_payload(
    empty_ledger: sqlite3.Connection, tmp_path: Path
) -> None:
    payload = metrics.insights(empty_ledger, "nobody", tmp_path)
    assert payload["current_version"] is None
    assert payload["trials"] is None
    assert payload["pass_at_1_by_version"] == []
    assert payload["pass_pow_k_by_version"] == []
    assert payload["memory_by_version"] == []
    assert payload["tool_stats_by_version"] == []
    assert payload["drift"]["tokens_saved"] == 0
    assert payload["issues"] == {"open": 0, "closed": 0}
    assert payload["graduated_count"] == 0
    assert payload["saturated"] is False
    assert payload["flagged_tasks"] == []


def test_compare_is_null_on_both_sides(empty_ledger: sqlite3.Connection, tmp_path: Path) -> None:
    assert metrics.compare(empty_ledger, "nobody", "c1", tmp_path) == {
        "agent_id": "nobody",
        "case_id": "c1",
        "current_version": None,
        "expected": None,
        "v0": None,
        "current": None,
    }


def test_insights_compare_reports_no_domains_and_no_ablation(
    empty_ledger: sqlite3.Connection, tmp_path: Path
) -> None:
    assert metrics.insights_compare(empty_ledger, tmp_path) == {
        "by_domain": {},
        "ablation": None,
    }


def test_metrics_survive_a_database_without_the_issues_table(tmp_path: Path) -> None:
    """W7 has not merged yet: an absent issues table must not crash insights."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, "
        "agent_id TEXT, agent_version INTEGER, run_id TEXT, lever TEXT, payload TEXT NOT NULL);"
    )
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, payload) VALUES "
        "('2026-09-06T10:00:00Z', 'issue_opened', 'a', 0, '{\"issue_id\": \"i1\"}')"
    )
    try:
        # No issues row anywhere: the event says one was opened, nothing says it closed.
        assert metrics.issue_stats(conn, "a") == {"open": 1, "closed": 0}
        assert metrics.insights(conn, "a", tmp_path)["issues"] == {
            "open": 1,
            "closed": 0,
        }
    finally:
        conn.close()
