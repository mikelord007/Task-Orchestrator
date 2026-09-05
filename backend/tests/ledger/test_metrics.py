"""Metrics over the seeded ledger.

Every expected value here is hand-computed from the fixture in ``seed.py`` --
none of it is produced by calling the code under test. Terminology follows
PLAN_ADDENDUM.md sec J: task/trial/grader.
"""

from __future__ import annotations

import json
import math
import sqlite3

import pytest

from backend.ledger import metrics
from backend.ledger.emit import emit as ledger_emit
from backend.tests.ledger.seed import AGENT_ID, SeededLedger, create_schema
from contracts.transcript import StepKind, Transcript

# Population std of the v0 and v1 train per-trial rates.
# v0: [0.75, 0.50, 0.75] -> sqrt(1/72);  v1: [1.00, 0.75, 0.75] -> sqrt(1/72)
STD_1_72 = math.sqrt(1 / 72)  # 0.11785113019775793
# v1 holdout per-trial rates [1.0, 0.5, 1.0] -> sqrt(1/18)
STD_1_18 = math.sqrt(1 / 18)  # 0.23570226039551584


# ---------------------------------------------------------------- pass@1


def test_pass_at_1_v0_train_matches_hand_computation(seeded: SeededLedger) -> None:
    # c1 1, c2 1, c3 2/3, c4 0 -> mean 2/3; per-trial [0.75, 0.50, 0.75]
    result = metrics.pass_at_1(seeded.conn, AGENT_ID, 0, "train")
    assert result["mean"] == pytest.approx(2 / 3)
    assert result["std"] == pytest.approx(STD_1_72)
    assert result["min"] == pytest.approx(0.5)
    assert result["max"] == pytest.approx(0.75)
    assert result["trials"] == 3
    assert result["task_count"] == 4


def test_pass_at_1_v1_train_improves_on_v0(seeded: SeededLedger) -> None:
    # c1 1, c2 1, c3 1, c4 1/3 -> mean 5/6; per-trial [1.0, 0.75, 0.75]
    result = metrics.pass_at_1(seeded.conn, AGENT_ID, 1, "train")
    assert result["mean"] == pytest.approx(5 / 6)
    assert result["std"] == pytest.approx(STD_1_72)
    assert result["min"] == pytest.approx(0.75)
    assert result["max"] == pytest.approx(1.0)


def test_pass_at_1_holdout_has_zero_spread_at_v0(seeded: SeededLedger) -> None:
    # h1 always passes, h2 never does: every trial scores exactly 0.5.
    result = metrics.pass_at_1(seeded.conn, AGENT_ID, 0, "holdout")
    assert result["mean"] == pytest.approx(0.5)
    assert result["std"] == pytest.approx(0.0)
    assert result["min"] == pytest.approx(0.5)
    assert result["max"] == pytest.approx(0.5)
    assert result["task_count"] == 2


def test_pass_at_1_holdout_v1(seeded: SeededLedger) -> None:
    result = metrics.pass_at_1(seeded.conn, AGENT_ID, 1, "holdout")
    assert result["mean"] == pytest.approx(5 / 6)
    assert result["std"] == pytest.approx(STD_1_18)
    assert result["min"] == pytest.approx(0.5)
    assert result["max"] == pytest.approx(1.0)


def test_pass_at_1_for_a_version_that_never_ran_is_null(seeded: SeededLedger) -> None:
    result = metrics.pass_at_1(seeded.conn, AGENT_ID, 5, "train")
    assert result == {
        "mean": None,
        "std": None,
        "min": None,
        "max": None,
        "trials": None,
        "task_count": 0,
    }


# ---------------------------------------------------------------- pass^k


def test_pass_pow_k_shares_the_std_min_max_of_pass_at_1(seeded: SeededLedger) -> None:
    """pass^k differs from pass@1 only in what `mean` measures."""
    at_1 = metrics.pass_at_1(seeded.conn, AGENT_ID, 0, "train")
    pow_k = metrics.pass_pow_k(seeded.conn, AGENT_ID, 0, "train")
    assert pow_k["std"] == pytest.approx(at_1["std"])
    assert pow_k["min"] == pytest.approx(at_1["min"])
    assert pow_k["max"] == pytest.approx(at_1["max"])
    assert pow_k["trials"] == at_1["trials"]
    assert pow_k["task_count"] == at_1["task_count"]


def test_pass_pow_k_v0_train_is_the_stable_fraction(seeded: SeededLedger) -> None:
    # c1, c2 stable (2 of 4 tasks) -> 0.5
    result = metrics.pass_pow_k(seeded.conn, AGENT_ID, 0, "train")
    assert result["mean"] == pytest.approx(0.5)


def test_pass_pow_k_v1_train_grows_as_c3_stabilizes(seeded: SeededLedger) -> None:
    # c1, c2, c3 stable (3 of 4 tasks) -> 0.75
    result = metrics.pass_pow_k(seeded.conn, AGENT_ID, 1, "train")
    assert result["mean"] == pytest.approx(0.75)


def test_pass_pow_k_holdout(seeded: SeededLedger) -> None:
    # v0: only h1 stable -> 0.5.  v1: only h1 stable (h2 flakes) -> 0.5.
    assert metrics.pass_pow_k(seeded.conn, AGENT_ID, 0, "holdout")["mean"] == pytest.approx(0.5)
    assert metrics.pass_pow_k(seeded.conn, AGENT_ID, 1, "holdout")["mean"] == pytest.approx(0.5)


# ------------------------------------------------------------- stable set


def test_stable_pass_set_excludes_the_flaky_task(seeded: SeededLedger) -> None:
    # c3 passes 2 of 3 trials at v0, so the gate must not protect it.
    assert metrics.stable_pass_set(seeded.conn, AGENT_ID, 0) == {"c1", "c2"}


def test_stable_pass_set_grows_once_the_flaky_task_settles(
    seeded: SeededLedger,
) -> None:
    assert metrics.stable_pass_set(seeded.conn, AGENT_ID, 1) == {"c1", "c2", "c3"}


def _tiny_case_result_payload(case_id: str, trial: int, *, passed: bool) -> dict:
    return {
        "case_id": case_id,
        "trial": trial,
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "tokens_in": 1,
        "tokens_out": 1,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "steps": 1,
        "transcript_path": f"runs/r1/{case_id}.t{trial}.json",
        "tool_calls": 0,
        "tool_errors": 0,
    }


def test_stable_pass_set_requires_every_declared_trial_present() -> None:
    """A task recorded for only 1 of 3 declared trials is not stable, even
    though the one trial recorded passed -- a partial run must not fool the
    gate (PLAN_ADDENDUM.md sec B: the gate accepts/rejects on pass^k)."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        ledger_emit(
            "run_started",
            agent_id="partial",
            agent_version=0,
            run_id="r1",
            conn=conn,
            payload={"split": "train", "case_count": 1, "trials": 3},
        )
        ledger_emit(
            "case_result",
            agent_id="partial",
            agent_version=0,
            run_id="r1",
            conn=conn,
            payload=_tiny_case_result_payload("only_one_trial", 0, passed=True),
        )
        ledger_emit(
            "run_finished",
            agent_id="partial",
            agent_version=0,
            run_id="r1",
            conn=conn,
            payload={
                "split": "train",
                "trials": 3,
                "pass_at_1": 1.0,
                "pass_pow_k": 1.0,
                "pass_rate_std": 0.0,
                "pass_rate_min": 1.0,
                "pass_rate_max": 1.0,
                "total_cost_usd": 0.0,
                "p50_latency_ms": 1,
                "p95_latency_ms": 1,
                "drift_count": 0,
                "tokens_saved_by_drift": 0,
            },
        )
        assert metrics.stable_pass_set(conn, "partial", 0) == set()
        assert metrics.pass_pow_k(conn, "partial", 0, "train")["mean"] == pytest.approx(0.0)
    finally:
        conn.close()


# --------------------------------------------------------- cost and latency


def test_cost_per_run_is_the_whole_run(seeded: SeededLedger) -> None:
    # 4 tasks x 3 trials x $0.01 at v0, x $0.005 at v1.
    assert metrics.cost_per_run(seeded.conn, AGENT_ID, 0, "train") == pytest.approx(0.12)
    assert metrics.cost_per_run(seeded.conn, AGENT_ID, 1, "train") == pytest.approx(0.06)


def test_latency_percentiles_interpolate(seeded: SeededLedger) -> None:
    # v0 train latencies are 1000, 1100, ... 2100 (12 values).
    # p50: k = 11*0.50 = 5.5  -> (1500 + 1600) / 2 = 1550
    # p95: k = 11*0.95 = 10.45 -> 2000*0.55 + 2100*0.45 = 2045
    assert metrics.latency_percentiles(seeded.conn, AGENT_ID, 0, "train") == {
        "p50": pytest.approx(1550.0),
        "p95": pytest.approx(2045.0),
    }
    # v1 train latencies are 500, 550, ... 1050.
    assert metrics.latency_percentiles(seeded.conn, AGENT_ID, 1, "train") == {
        "p50": pytest.approx(775.0),
        "p95": pytest.approx(1022.5),
    }


# ------------------------------------------------------------------- drift


def test_drift_stats(seeded: SeededLedger) -> None:
    stats = metrics.drift_stats(seeded.conn, AGENT_ID)
    assert stats["count_by_kind"] == {"loop": 2, "budget": 1, "step_limit": 1}
    # aborts only: (20000 - 15000) + (20000 - 18000)
    assert stats["tokens_saved"] == 7000
    # c3 was nudged twice; it passed on trial 2 and failed on trial 1.
    assert stats["cases_recovered_by_nudge"] == 1
    assert stats["count_by_version"] == {0: 3, 1: 1}


def test_drift_token_budget_is_read_from_the_environment(
    seeded: SeededLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DRIFT_TOKEN_BUDGET", "30000")
    stats = metrics.drift_stats(seeded.conn, AGENT_ID)
    assert stats["tokens_saved"] == (30000 - 15000) + (30000 - 18000)


# ------------------------------------------------- fixes, issues, lessons


def test_fixes_by_lever_counts_accepted_fixes_only(seeded: SeededLedger) -> None:
    assert metrics.fixes_by_lever(seeded.conn, AGENT_ID) == {"memory": 1}


def test_regressions_caught(seeded: SeededLedger) -> None:
    assert metrics.regressions_caught(seeded.conn, AGENT_ID) == 1


def test_issue_stats_joins_events_to_the_issues_table(seeded: SeededLedger) -> None:
    assert metrics.issue_stats(seeded.conn, AGENT_ID) == {"open": 1, "closed": 1}


def test_lessons_count(seeded: SeededLedger) -> None:
    assert metrics.lessons_count(seeded.conn) == 2


# ------------------------------------------------------------------ series


def test_series_by_version_has_one_row_per_version_and_split(
    seeded: SeededLedger,
) -> None:
    series = metrics.series_by_version(seeded.conn, AGENT_ID)
    expected_keys = [(0, "train"), (0, "holdout"), (1, "train"), (1, "holdout")]
    assert [(r["version"], r["split"]) for r in series["pass_at_1_by_version"]] == expected_keys
    assert [(r["version"], r["split"]) for r in series["pass_pow_k_by_version"]] == expected_keys

    at_1 = {(r["version"], r["split"]): r for r in series["pass_at_1_by_version"]}
    assert at_1[(0, "train")]["mean"] == pytest.approx(2 / 3)
    assert at_1[(1, "holdout")]["mean"] == pytest.approx(5 / 6)

    pow_k = {(r["version"], r["split"]): r for r in series["pass_pow_k_by_version"]}
    assert pow_k[(0, "train")]["mean"] == pytest.approx(0.5)
    assert pow_k[(1, "train")]["mean"] == pytest.approx(0.75)

    costs = {(r["version"], r["split"]): r for r in series["cost_by_version"]}
    assert costs[(0, "train")]["cost_per_run"] == pytest.approx(0.12)
    assert costs[(0, "train")]["cost_per_task"] == pytest.approx(0.03)
    assert costs[(1, "train")]["cost_per_run"] == pytest.approx(0.06)

    latencies = {(r["version"], r["split"]): r for r in series["latency_by_version"]}
    assert latencies[(1, "train")]["p50_ms"] == pytest.approx(775.0)


def test_series_skips_versions_with_no_finished_run(seeded: SeededLedger) -> None:
    # v2 was proposed and rejected; it never produced a finished run.
    series = metrics.series_by_version(seeded.conn, AGENT_ID)
    assert all(r["version"] != 2 for r in series["pass_at_1_by_version"])


# ----------------------------------------------------------------- markers


def test_markers_cover_every_annotation_kind(seeded: SeededLedger) -> None:
    found = metrics.markers(seeded.conn, AGENT_ID)
    kinds = [m["kind"] for m in found]
    assert kinds.count("issue_opened") == 2
    assert kinds.count("fix_accepted") == 1
    assert kinds.count("fix_rejected") == 1
    assert kinds.count("memory_demoted") == 1
    assert kinds.count("drift_cluster") == 2

    accepted = next(m for m in found if m["kind"] == "fix_accepted")
    assert accepted["version"] == 1
    assert accepted["lever"] == "memory"
    assert accepted["hypothesis"].startswith("The agent never learned")
    assert accepted["diagnosis"]
    assert accepted["metric_signal"].startswith("tool_calls_per_task fell")

    rejected = next(m for m in found if m["kind"] == "fix_rejected")
    assert rejected["reason"] == "regression"
    assert rejected["lever"] == "prompt"
    assert rejected["metric_signal"] is None

    clusters = {m["version"]: m for m in found if m["kind"] == "drift_cluster"}
    assert clusters[0]["count"] == 3
    assert clusters[0]["count_by_kind"] == {"loop": 2, "budget": 1}
    assert clusters[1]["count_by_kind"] == {"step_limit": 1}


def test_markers_are_ordered_by_timestamp(seeded: SeededLedger) -> None:
    found = metrics.markers(seeded.conn, AGENT_ID)
    timestamps = [m["ts"] for m in found]
    assert timestamps == sorted(timestamps)


# --------------------------------------------------- graduation, saturation


def test_graduated_count_is_distinct_tasks_ever_stabilized(
    seeded: SeededLedger,
) -> None:
    # c1, c2 stable from v0; c3 joins at v1; c4 never stabilizes.
    assert metrics.graduated_count(seeded.conn, AGENT_ID) == 3


def test_saturated_is_false_below_threshold(seeded: SeededLedger) -> None:
    # train pass@1 is 2/3 then 5/6 -- neither run clears 0.95.
    assert metrics.saturated(seeded.conn, AGENT_ID) is False


def test_saturated_needs_two_finished_train_runs() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        assert metrics.saturated(conn, "nobody") is False
    finally:
        conn.close()


def test_saturated_is_true_after_two_high_scoring_train_runs() -> None:
    """A dedicated tiny ledger: two consecutive train runs at >= 0.95 pass@1."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        for version in (0, 1):
            _insert_high_scoring_train_run(conn, version)
        assert metrics.saturated(conn, "sat_agent") is True
    finally:
        conn.close()


def test_zero_pass_tasks_needs_three_finished_train_runs(seeded: SeededLedger) -> None:
    # Only v0 and v1 have finished train runs in the main fixture.
    assert metrics.zero_pass_tasks(seeded.conn, AGENT_ID) == []


def test_zero_pass_tasks_flags_a_task_stuck_at_zero_for_three_versions() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        for version in range(3):
            _insert_train_run_with_a_dead_task(conn, version)
        assert metrics.zero_pass_tasks(conn, "flag_agent") == ["dead"]
    finally:
        conn.close()


def _insert_high_scoring_train_run(conn: sqlite3.Connection, version: int) -> None:
    """Two tasks, both passing every trial -- pass@1 = 1.0 >= 0.95."""
    run_id = f"run_v{version}"
    ts = f"2026-09-06T1{version}:00:00Z"
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
        "(?, 'run_started', 'sat_agent', ?, ?, ?)",
        (ts, version, run_id, '{"split": "train", "trials": 2, "case_count": 2}'),
    )
    for task_id in ("t1", "t2"):
        for trial in (0, 1):
            conn.execute(
                "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) "
                "VALUES (?, 'case_result', 'sat_agent', ?, ?, ?)",
                (
                    ts,
                    version,
                    run_id,
                    f'{{"case_id": "{task_id}", "trial": {trial}, "passed": true}}',
                ),
            )
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
        "(?, 'run_finished', 'sat_agent', ?, ?, '{\"split\": \"train\"}')",
        (ts, version, run_id),
    )
    conn.commit()


def _insert_train_run_with_a_dead_task(conn: sqlite3.Connection, version: int) -> None:
    """A live task that always passes, and 'dead' which never does."""
    run_id = f"run_v{version}"
    ts = f"2026-09-06T1{version}:00:00Z"
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
        "(?, 'run_started', 'flag_agent', ?, ?, ?)",
        (ts, version, run_id, json.dumps({"split": "train", "trials": 1})),
    )
    for case_id, passed in (("live", True), ("dead", False)):
        conn.execute(
            "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
            "(?, 'case_result', 'flag_agent', ?, ?, ?)",
            (ts, version, run_id, json.dumps({"case_id": case_id, "trial": 0, "passed": passed})),
        )
    conn.execute(
        "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
        "(?, 'run_finished', 'flag_agent', ?, ?, ?)",
        (ts, version, run_id, json.dumps({"split": "train"})),
    )
    conn.commit()


# ----------------------------------------------------- memory and tool use


def test_rule_stats_credits_hits_and_misses_from_graded_results(
    seeded: SeededLedger,
) -> None:
    stats = metrics.rule_stats(seeded.conn, AGENT_ID)
    # r1: 9 v1-train passes + h1's 3 passes + h2's 2 passes / 1 fail
    assert stats["r1"] == {"hits": 14, "misses": 1, "uses": 15}
    # r2: injected on the three tasks that always pass at v1
    assert stats["r2"] == {"hits": 9, "misses": 0, "uses": 9}
    # r3: injected only on c4, which passes 1 of 3 at v1 -- this is why it is demoted
    assert stats["r3"] == {"hits": 1, "misses": 2, "uses": 3}


def test_memory_by_version(seeded: SeededLedger) -> None:
    growth = metrics.memory_by_version(seeded.conn, AGENT_ID, seeded.root)
    assert [row["version"] for row in growth] == [0, 1, 2]

    assert growth[0]["rules"] == 0
    assert growth[0]["tool_notes"] == 0
    assert growth[0]["mean_confidence"] is None
    assert growth[0]["demotions"] == 0

    # 3 rules written at v1, 1 demoted -> 2 active; confidences 0.9/0.8/0.4 on disk.
    assert growth[1]["rules_written"] == 3
    assert growth[1]["rules"] == 2
    assert growth[1]["tool_notes"] == 1
    assert growth[1]["mean_confidence"] == pytest.approx(0.7)
    assert growth[1]["demotions"] == 1

    # v2 was rejected: memory carries forward, no snapshot on disk.
    assert growth[2]["rules"] == 2
    assert growth[2]["tool_notes"] == 1
    assert growth[2]["mean_confidence"] is None


def test_tool_call_stats_reads_transcript_detail(seeded: SeededLedger) -> None:
    stats = metrics.tool_call_stats(seeded.conn, AGENT_ID, 0, "train", seeded.root)
    assert stats["aggregate"] == {
        "calls": pytest.approx(9.0),
        "errors": pytest.approx(1.0),
        "redundant": pytest.approx(2.0),
        "tool_tokens": pytest.approx(450.0),
        "latency_ms": pytest.approx(1550.0),
        "tool_tokens_estimated": False,
    }
    # c4 runs at trial-indices 3, 7, 11 -> latencies 1300, 1700, 2100.
    assert stats["tasks"]["c4"]["calls"] == pytest.approx(9.0)
    assert stats["tasks"]["c4"]["latency_ms"] == pytest.approx(1700.0)


def test_tool_call_stats_v1_has_no_redundancy(seeded: SeededLedger) -> None:
    stats = metrics.tool_call_stats(seeded.conn, AGENT_ID, 1, "train", seeded.root)
    assert stats["aggregate"]["calls"] == pytest.approx(4.0)
    assert stats["aggregate"]["errors"] == pytest.approx(0.0)
    assert stats["aggregate"]["redundant"] == pytest.approx(0.0)
    assert stats["aggregate"]["tool_tokens"] == pytest.approx(240.0)


def test_tool_call_stats_falls_back_to_case_result_without_a_transcript() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
            "('2026-09-06T10:00:00Z', 'run_started', 'a', 0, 'r1', "
            '\'{"split": "train", "trials": 1}\')'
        )
        conn.execute(
            "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
            "('2026-09-06T10:00:01Z', 'case_result', 'a', 0, 'r1', "
            '\'{"case_id": "c1", "trial": 0, "passed": true, "tool_calls": 5, '
            '"tool_errors": 1, "latency_ms": 200}\')'
        )
        conn.execute(
            "INSERT INTO events (ts, kind, agent_id, agent_version, run_id, payload) VALUES "
            "('2026-09-06T10:00:02Z', 'run_finished', 'a', 0, 'r1', '{\"split\": \"train\"}')"
        )
        conn.commit()
        stats = metrics.tool_call_stats(conn, "a", 0, "train")
        assert stats["aggregate"]["calls"] == pytest.approx(5.0)
        assert stats["aggregate"]["errors"] == pytest.approx(1.0)
        assert stats["aggregate"]["redundant"] is None
        assert stats["aggregate"]["tool_tokens"] is None
        assert stats["aggregate"]["tool_tokens_estimated"] is None
    finally:
        conn.close()


def test_tool_call_stats_uses_normalized_args_and_estimated_flag(tmp_path) -> None:
    """W2's transcripts carry ``normalized_args`` on tool_call steps (sorted
    keys, stripped/lowercased strings -- what the loop-drift detector groups
    on) and ``tokens_estimated`` on tool_return steps. Both are extensions
    beyond ``contracts/transcript.py`` (read via ``getattr``, since
    ``TranscriptStep`` allows extra fields); redundancy detection must group
    on ``normalized_args`` when present so it agrees with the drift watchdog."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        run_id = "run1"
        Transcript(
            run_id=run_id,
            case_id="c1",
            trial=0,
            agent_id="a",
            version=0,
            started_ts="2026-09-06T10:00:00Z",
            finished_ts="2026-09-06T10:00:01Z",
            steps=[
                {
                    "i": 0,
                    "ts": "2026-09-06T10:00:00Z",
                    "kind": StepKind.tool_call,
                    "tool": "list_issues",
                    "args": {"State": "Open", "Label": " Bug "},
                    "normalized_args": '{"label": "bug", "state": "open"}',
                },
                {
                    "i": 1,
                    "ts": "2026-09-06T10:00:00Z",
                    "kind": StepKind.tool_return,
                    "tool": "list_issues",
                    "result": "ok",
                    "tokens_in": 40,
                    "tokens_estimated": True,
                },
                {
                    "i": 2,
                    "ts": "2026-09-06T10:00:00Z",
                    "kind": StepKind.tool_call,
                    "tool": "list_issues",
                    "args": {"state": "open", "label": "bug"},
                    "normalized_args": '{"label": "bug", "state": "open"}',
                },
                {
                    "i": 3,
                    "ts": "2026-09-06T10:00:00Z",
                    "kind": StepKind.tool_return,
                    "tool": "list_issues",
                    "result": "ok",
                    "tokens_in": 40,
                },
            ],
            final_output={"labels": []},
            tokens_in=80,
            tokens_out=10,
            tool_calls=2,
            tool_errors=0,
        ).write(root=tmp_path / "runs")

        ledger_emit(
            "run_started",
            agent_id="a",
            agent_version=0,
            run_id=run_id,
            conn=conn,
            payload={"split": "train", "case_count": 1, "trials": 1},
        )
        ledger_emit(
            "case_result",
            agent_id="a",
            agent_version=0,
            run_id=run_id,
            conn=conn,
            payload={
                "case_id": "c1",
                "trial": 0,
                "passed": True,
                "score": 1.0,
                "tokens_in": 80,
                "tokens_out": 10,
                "cost_usd": 0.0,
                "latency_ms": 10,
                "steps": 4,
                "transcript_path": f"runs/{run_id}/c1.t0.json",
                "tool_calls": 2,
                "tool_errors": 0,
            },
        )
        ledger_emit(
            "run_finished",
            agent_id="a",
            agent_version=0,
            run_id=run_id,
            conn=conn,
            payload={
                "split": "train",
                "trials": 1,
                "pass_at_1": 1.0,
                "pass_pow_k": 1.0,
                "pass_rate_std": 0.0,
                "pass_rate_min": 1.0,
                "pass_rate_max": 1.0,
                "total_cost_usd": 0.0,
                "p50_latency_ms": 10,
                "p95_latency_ms": 10,
                "drift_count": 0,
                "tokens_saved_by_drift": 0,
            },
        )

        stats = metrics.tool_call_stats(conn, "a", 0, "train", tmp_path)
        assert stats["aggregate"]["calls"] == pytest.approx(2.0)
        # Different raw args, same normalized_args -> grouped as one redundant call.
        assert stats["aggregate"]["redundant"] == pytest.approx(1.0)
        assert stats["aggregate"]["tool_tokens_estimated"] is True

        rows = metrics.tool_stats_by_version(conn, "a", tmp_path)
        assert rows[0]["tool_tokens_estimated"] is True
    finally:
        conn.close()


def test_tool_stats_by_version_falls_between_versions(seeded: SeededLedger) -> None:
    rows = metrics.tool_stats_by_version(seeded.conn, AGENT_ID, seeded.root)
    by_key = {(r["version"], r["split"]): r for r in rows}
    assert set(by_key) == {(0, "train"), (0, "holdout"), (1, "train"), (1, "holdout")}

    v0 = by_key[(0, "train")]
    assert v0["calls"] == pytest.approx(9.0)
    assert v0["errors"] == pytest.approx(1.0)
    assert v0["redundant"] == pytest.approx(2.0)
    assert v0["tool_tokens"] == pytest.approx(450.0)
    assert v0["latency_ms"] == pytest.approx(1550.0)

    v1 = by_key[(1, "train")]
    assert v1["calls"] == pytest.approx(4.0)
    assert v1["redundant"] == pytest.approx(0.0)
    assert v1["tool_tokens"] == pytest.approx(240.0)


# --------------------------------------------------------------- fix cards


def test_fix_cards_are_newest_first_and_complete(seeded: SeededLedger) -> None:
    cards = metrics.fix_cards(seeded.conn, AGENT_ID)
    assert [c["to_version"] for c in cards] == [2, 1]

    accepted = cards[1]
    assert accepted["status"] == "accepted"
    assert accepted["lever"] == "memory"
    assert accepted["from_version"] == 0
    assert accepted["failing_group"] == {
        "signature": "wrong_component",
        "tag": "windows",
        "count": 1,
        "case_ids": ["c4"],
    }
    assert accepted["hypothesis"]
    assert accepted["diagnosis"]
    # metric_signal is contract-restricted to lever=tools fixes (api.md);
    # this fix is lever=memory, so the card must null it out even though the
    # raw fix_proposed event carries one (see markers(), which is not so
    # restricted and does surface it -- test_markers_cover_every_annotation_kind).
    assert accepted["metric_signal"] is None
    assert accepted["files_touched"] == [
        "memory/rules.jsonl",
        "memory/tool_notes.jsonl",
    ]
    assert accepted["diff_url"] == f"/agents/{AGENT_ID}/fixes/1/diff"
    assert accepted["before"] == {
        "pass_at_1": pytest.approx(2 / 3),
        "pass_pow_k": pytest.approx(0.5),
        "group_pass": pytest.approx(0.0),
        "cost_per_run": pytest.approx(0.12),
        "tool_calls_per_task": pytest.approx(9.0),
    }
    assert accepted["after"] == {
        "pass_at_1": pytest.approx(5 / 6),
        "pass_pow_k": pytest.approx(0.75),
        "group_pass": pytest.approx(1 / 3),
        "holdout_pass_at_1": pytest.approx(5 / 6),
        "holdout_pass_pow_k": pytest.approx(0.5),
        "cost_per_run": pytest.approx(0.06),
        "tool_calls_per_task": pytest.approx(4.0),
    }
    assert accepted["regressed_case_ids"] == []


def test_memory_fix_cards_carry_their_entries(seeded: SeededLedger) -> None:
    accepted = next(
        c for c in metrics.fix_cards(seeded.conn, AGENT_ID) if c["status"] == "accepted"
    )
    entries = accepted["memory_entries"]
    assert [e["entry_id"] for e in entries] == ["r1", "r2", "r3", "t1"]
    assert [e["kind"] for e in entries] == ["rule", "rule", "rule", "tool_note"]
    assert entries[0]["evidence_case_ids"] == ["c4"]


def test_metric_signal_passes_through_for_a_tools_lever_fix() -> None:
    """The only lever the contract actually shows metric_signal for."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        ledger_emit(
            "fix_proposed",
            agent_id="a",
            agent_version=0,
            lever="tools",
            conn=conn,
            payload={
                **_tiny_fix_proposed_payload("h"),
                "metric_signal": "12 redundant list_issues calls/task",
            },
        )
        ledger_emit(
            "fix_accepted",
            agent_id="a",
            agent_version=1,
            lever="tools",
            conn=conn,
            payload={
                "to_version": 1,
                "pass_at_1_before": 0.5,
                "pass_at_1_after": 0.6,
                "pass_pow_k_before": 0.5,
                "pass_pow_k_after": 0.6,
                "group_pass_before": 0.5,
                "group_pass_after": 0.6,
                "holdout_pass_at_1_after": 0.6,
                "holdout_pass_pow_k_after": 0.6,
                "cost_per_run_before": 1.0,
                "cost_per_run_after": 0.9,
                "tool_calls_per_task_before": 12.0,
                "tool_calls_per_task_after": 4.0,
            },
        )
        card = metrics.fix_cards(conn, "a")[0]
        assert card["lever"] == "tools"
        assert card["metric_signal"] == "12 redundant list_issues calls/task"
    finally:
        conn.close()


def test_rejected_fix_card_lists_regressed_tasks_and_derives_before(
    seeded: SeededLedger,
) -> None:
    rejected = cards_by_version(seeded)[2]
    assert rejected["status"] == "rejected"
    assert rejected["lever"] == "prompt"
    assert rejected["regressed_case_ids"] == ["c2"]
    assert rejected["metric_signal"] is None
    # fix_rejected carries only the candidate's pass@1, so `before` comes from v1.
    assert rejected["before"]["pass_at_1"] == pytest.approx(5 / 6)
    assert rejected["before"]["pass_pow_k"] == pytest.approx(0.75)
    assert rejected["before"]["cost_per_run"] == pytest.approx(0.06)
    assert rejected["before"]["tool_calls_per_task"] == pytest.approx(4.0)
    assert rejected["after"]["pass_at_1"] == pytest.approx(0.75)
    assert rejected["after"]["pass_pow_k"] is None
    assert "memory_entries" not in rejected


def cards_by_version(seeded: SeededLedger) -> dict[int, dict]:
    return {c["to_version"]: c for c in metrics.fix_cards(seeded.conn, AGENT_ID)}


def _tiny_fix_proposed_payload(
    hypothesis: str, diff_path: str = "agents/a/v1/CHANGES.diff"
) -> dict:
    return {
        "from_version": 0,
        "to_version": 1,
        "failing_group": {"signature": "x", "case_ids": [], "count": 0},
        "hypothesis": hypothesis,
        "diagnosis": "d",
        "diff_path": diff_path,
        "diff_summary": "s",
    }


def test_fix_cards_omits_a_proposal_with_no_verdict_yet() -> None:
    """contracts/api.md: a fix still in flight is omitted, not given status='proposed'."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        ledger_emit(
            "fix_proposed",
            agent_id="a",
            agent_version=0,
            lever="prompt",
            conn=conn,
            payload=_tiny_fix_proposed_payload("h"),
        )
        assert metrics.fix_cards(conn, "a") == []
    finally:
        conn.close()


def test_fix_cards_keeps_the_newest_proposal_per_to_version() -> None:
    """Two proposals at one to_version must not both spawn a card sharing one outcome."""
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        for hypothesis in ("first guess", "second guess"):
            ledger_emit(
                "fix_proposed",
                agent_id="a",
                agent_version=0,
                lever="prompt",
                conn=conn,
                payload=_tiny_fix_proposed_payload(hypothesis),
            )
        ledger_emit(
            "fix_rejected",
            agent_id="a",
            agent_version=1,
            lever="prompt",
            conn=conn,
            payload={
                "to_version": 1,
                "reason": "no_gain",
                "regressed_case_ids": [],
                "candidate_pass_at_1": 0.5,
            },
        )
        cards = metrics.fix_cards(conn, "a")
        assert len(cards) == 1
        assert cards[0]["hypothesis"] == "second guess"
    finally:
        conn.close()


def test_fix_diff_reads_the_file_on_disk(seeded: SeededLedger) -> None:
    diff = metrics.fix_diff(seeded.conn, AGENT_ID, 1, seeded.root)
    assert diff is not None
    assert diff.startswith("--- a/memory/rules.jsonl")
    assert metrics.fix_diff(seeded.conn, AGENT_ID, 99, seeded.root) is None


def test_fix_diff_refuses_a_path_outside_the_repo_root(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn)
        ledger_emit(
            "fix_proposed",
            agent_id="a",
            agent_version=0,
            lever="prompt",
            conn=conn,
            payload=_tiny_fix_proposed_payload("h", diff_path="../secret.txt"),
        )
        assert metrics.fix_diff(conn, "a", 1, root) is None
    finally:
        conn.close()


# ----------------------------------------------------------------- compare


def test_compare_shows_the_output_getting_better(seeded: SeededLedger) -> None:
    result = metrics.compare(seeded.conn, AGENT_ID, "c4", seeded.root)
    assert result["expected"] == {"labels": ["bug", "windows"], "component": "pty"}

    v0 = result["v0"]
    assert v0["output"] == {"labels": ["bug"], "component": "core"}
    assert v0["passed"] is False
    assert v0["rules_injected"] == []
    assert v0["tool_calls"] == 9
    assert v0["tokens"] == 1000
    assert v0["trial"] == 0

    current = result["current"]
    assert result["current_version"] == 1
    assert current["output"] == {"labels": ["bug", "windows"], "component": "pty"}
    assert current["passed"] is True
    assert current["rules_injected"] == ["r3"]
    assert current["tool_calls"] == 4
    assert current["tokens"] == 500
    assert current["trial"] == 0


def test_compare_returns_null_for_a_task_with_no_result(seeded: SeededLedger) -> None:
    result = metrics.compare(seeded.conn, AGENT_ID, "nope", seeded.root)
    assert result["v0"] is None
    assert result["current"] is None
    assert result["expected"] is None


# ---------------------------------------------------------------- insights


def test_insights_assembles_every_section(seeded: SeededLedger) -> None:
    payload = metrics.insights(seeded.conn, AGENT_ID, seeded.root)
    assert payload["agent_id"] == AGENT_ID
    assert payload["domain"] == "github_triage"
    assert payload["current_version"] == 1
    assert payload["trials"] == 3
    assert len(payload["pass_at_1_by_version"]) == 4
    assert len(payload["pass_pow_k_by_version"]) == 4
    assert payload["fixes_by_lever"] == {"memory": 1}
    assert payload["regressions_caught"] == 1
    assert payload["issues"] == {"open": 1, "closed": 1}
    assert payload["lessons_count"] == 2
    assert payload["drift"]["tokens_saved"] == 7000
    assert payload["markers"]
    assert len(payload["memory_by_version"]) == 3
    assert len(payload["tool_stats_by_version"]) == 4
    assert payload["graduated_count"] == 3
    assert payload["saturated"] is False
    assert payload["flagged_tasks"] == []
    assert payload["rule_stats"]["r3"]["misses"] == 2


def test_insights_compare_groups_by_domain(seeded: SeededLedger) -> None:
    payload = metrics.insights_compare(seeded.conn, seeded.root)
    assert set(payload["by_domain"]) == {"github_triage", "ticket_triage"}
    assert payload["by_domain"]["github_triage"][0]["agent_id"] == AGENT_ID
    assert payload["by_domain"]["ticket_triage"][0]["pass_at_1_by_version"][0][
        "mean"
    ] == pytest.approx(0.5)
    assert payload["ablation"] is None


def test_insights_compare_includes_the_ablation_report_when_present(
    seeded_with_ablation: SeededLedger,
) -> None:
    payload = metrics.insights_compare(seeded_with_ablation.conn, seeded_with_ablation.root)
    assert payload["ablation"]["playbook_on"]["holdout_mean"] == pytest.approx(0.58)
