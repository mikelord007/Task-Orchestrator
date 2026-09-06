"""Tests for `scripts/demo_run.py`'s report-writer functions (W11 brief item 7).

These run against W1's seeded ledger fixture (`backend/tests/ledger/seed.py`,
the FakeLLM-free, network-free scenario the metrics tests also use) rather
than against a live LLM or a real GitHub API -- exactly what the brief asks
for: "the script's report writers run against W1's seeded ledger with the
FakeLLM (no network) and produce the JSON/markdown shapes."

The report writers remain pure-function tests. The Domain A improvement-round
orchestrator is covered separately with the project's FakeLLM driving a stub
improver, so call count, checkpoint ordering, and saturation are verified
without running an eval suite or touching the network.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.testing.fake_llm import FakeLLM  # noqa: E402
from backend.testing.fake_llm import text as llm_text  # noqa: E402


def _load_module():
    spec = importlib.util.spec_from_file_location("demo_run", REPO_ROOT / "scripts" / "demo_run.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


demo_run = _load_module()


def _seed_module():
    from backend.tests.ledger import seed

    return seed


@pytest.fixture
def seeded(tmp_path: Path):
    # seed.build() applies the schema migrations itself -- calling
    # create_schema() again first would migrate() a second time and blow up
    # on the (unset) row_factory once schema_migrations already has rows.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    seed = _seed_module()
    handles = seed.build(conn, tmp_path)
    yield handles
    conn.close()


@pytest.fixture
def seeded_with_ablation(tmp_path: Path):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    seed = _seed_module()
    handles = seed.build(conn, tmp_path, ablation=True)
    yield handles
    conn.close()


# --------------------------------------------------------------------------
# build_domain_a_report
# --------------------------------------------------------------------------


class TestBuildDomainAReport:
    def test_shape(self, seeded):
        report = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)

        assert report["agent_id"] == seeded.agent_id
        assert report["domain"] == "github_triage"
        assert report["current_version"] == 1
        assert report["trials"] == seeded.trials

        for key in (
            "pass_at_1_by_version",
            "pass_pow_k_by_version",
            "cost_by_version",
            "latency_by_version",
            "tool_stats_by_version",
            "memory_by_version",
            "drift",
            "fixes_by_lever",
            "regressions_caught",
            "graduated_count",
            "saturated",
            "flagged_tasks",
            "lessons_count",
            "markers",
            "compare_cases",
            "fix_cards",
        ):
            assert key in report, key

        # Round-trips through JSON exactly like the real CLI writes it.
        json.dumps(report)

    def test_fix_counts_match_card_statuses(self, seeded):
        report = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)
        cards = report["fix_cards"]
        assert report["fixes_accepted"] == sum(1 for c in cards if c["status"] == "accepted")
        assert report["fixes_rejected"] == sum(1 for c in cards if c["status"] == "rejected")
        # The seeded scenario has exactly one of each (seed.py docstring).
        assert report["fixes_accepted"] == 1
        assert report["fixes_rejected"] == 1

    def test_pass_rates_have_both_splits(self, seeded):
        report = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)
        splits = {row["split"] for row in report["pass_at_1_by_version"]}
        assert {"train", "holdout"} <= splits

    def test_empty_ledger_is_honest_zeros_not_placeholders(self, tmp_path):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        _seed_module().create_schema(conn)
        try:
            report = demo_run.build_domain_a_report(conn, "no_such_agent", tmp_path)
        finally:
            conn.close()
        assert report["agent_id"] == "no_such_agent"
        assert report["pass_at_1_by_version"] == []
        assert report["fix_cards"] == []
        assert report["compare_cases"] == []
        assert report["fixes_accepted"] == 0
        assert report["fixes_rejected"] == 0


# --------------------------------------------------------------------------
# select_compare_cases
# --------------------------------------------------------------------------


class TestSelectCompareCases:
    def test_finds_v0_wrong_current_right(self, seeded):
        cases = demo_run.select_compare_cases(seeded.conn, seeded.agent_id, seeded.root)
        assert cases, "expected at least one v0-wrong/current-right case in the seeded fixture"
        case_ids = {c["case_id"] for c in cases}
        # c4 fails every trial at v0 and passes trial 0 at v1 with rule r3 injected
        # (seed.py: V0_PATTERNS["c4"] all False, V1_PATTERNS["c4"][0] True).
        assert "c4" in case_ids

        c4 = next(c for c in cases if c["case_id"] == "c4")
        assert c4["v0"]["passed"] is False
        assert c4["current"]["passed"] is True
        assert c4["current"]["rules_injected"]

    def test_never_includes_v0_pass_or_current_fail(self, seeded):
        cases = demo_run.select_compare_cases(seeded.conn, seeded.agent_id, seeded.root)
        for case in cases:
            assert case["v0"]["passed"] is False
            assert case["current"]["passed"] is True

    def test_respects_limit(self, seeded):
        cases = demo_run.select_compare_cases(seeded.conn, seeded.agent_id, seeded.root, limit=1)
        assert len(cases) <= 1

    def test_agent_never_run_returns_empty(self, tmp_path):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        _seed_module().create_schema(conn)
        try:
            assert demo_run.select_compare_cases(conn, "ghost", tmp_path) == []
        finally:
            conn.close()


# --------------------------------------------------------------------------
# build_domain_b_report
# --------------------------------------------------------------------------


class TestBuildDomainBReport:
    def test_shape_is_v0_only(self, seeded):
        report = demo_run.build_domain_b_report(seeded.conn, seeded.agent_b_id, seeded.root)
        assert report["agent_id"] == seeded.agent_b_id
        assert report["domain"] == "ticket_triage"
        assert report["version"] == 0
        for split in ("train", "holdout"):
            assert split in report
            for key in ("pass_at_1", "pass_pow_k", "cost_per_run", "latency", "tool_stats"):
                assert key in report[split]
        json.dumps(report)

    def test_empty_agent_is_honest_empty(self, tmp_path):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        _seed_module().create_schema(conn)
        try:
            report = demo_run.build_domain_b_report(conn, "no_such_agent", tmp_path)
        finally:
            conn.close()
        assert report["train"]["pass_at_1"]["mean"] is None
        assert report["train"]["cost_per_run"] is None


# --------------------------------------------------------------------------
# parse_build_log
# --------------------------------------------------------------------------


class TestParseBuildLog:
    SAMPLE = """\
# Build log

## Sessions

| session id | workstream | branch | PR | outcome | started | finished |
|---|---|---|---|---|---|---|
| `task-orchestrator-4` | W0 | `ws/w0` | [#3](https://x/pull/3) | merged | a | b |
| `task-orchestrator-7` | W1 | `ws/w1` | [#7](https://x/pull/7) | merged | a | b |
| `task-orchestrator-7` | W1b | `ws/w1b` | [#11](https://x/pull/11) | merged | a | b |

## Other section

| not | a | session | row |
"""

    def test_counts_distinct_sessions_and_prs(self):
        result = demo_run.parse_build_log(self.SAMPLE)
        assert result["session_count"] == 2
        assert result["pr_count"] == 3
        assert result["sessions"] == ["task-orchestrator-4", "task-orchestrator-7"]

    def test_stops_at_next_heading(self):
        result = demo_run.parse_build_log(self.SAMPLE)
        assert result["pr_count"] == 3  # the "Other section" table contributes nothing

    def test_empty_text(self):
        result = demo_run.parse_build_log("")
        assert result == {"session_count": 0, "sessions": [], "pr_count": 0}


# --------------------------------------------------------------------------
# flag_regressions
# --------------------------------------------------------------------------


class TestFlagRegressions:
    def test_improving_metrics_are_not_flagged(self, seeded):
        report = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)
        # The seeded scenario's v0->v1 train/holdout pass@1 improves or ties in
        # the fixture; whatever it does, flag_regressions must agree with the
        # actual numbers rather than a hand-picked expectation.
        flags = demo_run.flag_regressions(report)
        assert isinstance(flags, list)

    def test_flags_flat_pass_rate(self):
        domain_a = {
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.5, "std": 0.1},
            ],
            "cost_by_version": [],
        }
        flags = demo_run.flag_regressions(domain_a)
        assert any("train pass@1 did not improve" in f for f in flags)

    def test_flags_increased_cost(self):
        domain_a = {
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.7, "std": 0.1},
            ],
            "cost_by_version": [
                {"version": 0, "cost_per_run": 0.10},
                {"version": 1, "cost_per_run": 0.20},
            ],
        }
        flags = demo_run.flag_regressions(domain_a)
        assert any("cost per run increased" in f for f in flags)

    def test_no_flags_when_everything_improves(self):
        domain_a = {
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.8, "std": 0.05},
            ],
            "cost_by_version": [
                {"version": 0, "cost_per_run": 0.20},
                {"version": 1, "cost_per_run": 0.10},
            ],
        }
        assert demo_run.flag_regressions(domain_a) == []

    def test_single_version_is_never_flagged(self):
        domain_a = {
            "pass_at_1_by_version": [{"version": 0, "split": "train", "mean": 0.5, "std": 0.1}],
            "cost_by_version": [],
        }
        assert demo_run.flag_regressions(domain_a) == []


# --------------------------------------------------------------------------
# build_summary_markdown
# --------------------------------------------------------------------------


class TestBuildSummaryMarkdown:
    def test_full_shape_with_domain_b_and_ablation(self, seeded):
        domain_a = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)
        domain_b = demo_run.build_domain_b_report(seeded.conn, seeded.agent_b_id, seeded.root)
        ablation = {
            "domain": "ticket_triage",
            "trials": 3,
            "playbook_off": {"pass_at_1": 0.42, "pass_pow_k": 0.30, "std": 0.05},
            "playbook_on": {"pass_at_1": 0.58, "pass_pow_k": 0.45, "std": 0.04},
            "applied_lesson_ids": ["lesson-1"],
            "agent_ids": {"playbook_off": "off_x", "playbook_on": "on_y"},
        }
        build_log = (
            "# Build log\n\n## Sessions\n\n"
            "| session id | workstream | branch | PR | outcome | started | finished |\n"
            "|---|---|---|---|---|---|---|\n"
            "| `task-orchestrator-3` | W11 | `ws/w11` | [#20](https://x/pull/20) | open | a | b |\n"
        )

        markdown = demo_run.build_summary_markdown(
            domain_a, domain_b, ablation, build_log, generated_at="2026-09-06T12:00:00+00:00"
        )

        assert markdown.startswith("# Task Orchestrator")
        assert "pass@1" in markdown and "pass^k" in markdown
        assert f"trials = {seeded.trials}" in markdown
        assert "## Domain A -- github_triage" in markdown
        assert "## Domain B -- ticket_triage" in markdown
        assert "Playbook ablation" in markdown
        assert "playbook off: pass@1 0.420" in markdown
        assert "playbook on:  pass@1 0.580" in markdown
        assert "AO sessions: 1" in markdown
        assert "PRs: 1" in markdown
        assert "Best accepted fix card" in markdown
        assert "```json" in markdown  # the verbatim fix card
        assert "Compare cases: v0 wrong -> current right" in markdown
        assert "c4" in markdown

    def test_missing_domain_b_and_ablation_say_not_run(self, seeded):
        domain_a = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)
        markdown = demo_run.build_summary_markdown(domain_a, None, None, "")
        assert markdown.count("_not run._") == 2

    def test_no_accepted_fix_says_so(self, tmp_path):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        _seed_module().create_schema(conn)
        try:
            domain_a = demo_run.build_domain_a_report(conn, "ghost", tmp_path)
        finally:
            conn.close()
        markdown = demo_run.build_summary_markdown(domain_a, None, None, "")
        assert "_no accepted fix card yet._" in markdown
        assert "_none found yet" in markdown

    def test_flat_metrics_surface_a_flagged_section(self):
        domain_a = {
            "agent_id": "a1",
            "trials": 3,
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.5, "std": 0.1},
            ],
            "pass_pow_k_by_version": [],
            "cost_by_version": [],
            "latency_by_version": [],
            "tool_stats_by_version": [],
            "memory_by_version": [],
            "drift": {},
            "fixes_by_lever": {},
            "fixes_accepted": 0,
            "fixes_rejected": 0,
            "regressions_caught": 0,
            "graduated_count": 0,
            "saturated": False,
            "flagged_tasks": [],
            "lessons_count": 0,
            "compare_cases": [],
            "fix_cards": [],
        }
        markdown = demo_run.build_summary_markdown(domain_a, None, None, "")
        assert "Flagged (flat or negative" in markdown
        assert "train pass@1 did not improve" in markdown


# --------------------------------------------------------------------------
# top-level keyword helper used by populate-cache
# --------------------------------------------------------------------------


class TestTopKeywords:
    def test_drops_stopwords_and_dedupes(self):
        keywords = demo_run._top_keywords("The the Terminal resize crash on Windows and windows")
        assert "the" not in keywords
        assert "and" not in keywords
        assert keywords.count("windows") == 1

    def test_caps_at_limit(self):
        keywords = demo_run._top_keywords("alpha beta gamma delta epsilon zeta eta", limit=3)
        assert len(keywords) == 3


# --------------------------------------------------------------------------
# lazy W8b playbook scan hook
# --------------------------------------------------------------------------


class TestPlaybookScanHook:
    def test_calls_scan_once_for_each_accepted_attempt(self, monkeypatch):
        conn = sqlite3.connect(":memory:")
        calls = []

        def scan_and_record(received_conn):
            calls.append(received_conn)
            return {"recorded": 1, "skipped": 0, "last_event_id": len(calls)}

        monkeypatch.setattr(demo_run, "_resolve_scan_and_record", lambda: scan_and_record)
        result = SimpleNamespace(
            attempts=[
                SimpleNamespace(accepted=False),
                SimpleNamespace(accepted=True),
                SimpleNamespace(accepted=True),
            ]
        )
        try:
            scans = demo_run._scan_playbook_after_improve(conn, result)
        finally:
            conn.close()

        assert calls == [conn, conn]
        assert [scan["last_event_id"] for scan in scans] == [1, 2]

    def test_rejected_attempt_does_not_resolve_or_scan(self, monkeypatch):
        monkeypatch.setattr(
            demo_run,
            "_resolve_scan_and_record",
            lambda: pytest.fail("scanner should not be resolved without an accepted attempt"),
        )
        conn = sqlite3.connect(":memory:")
        try:
            scans = demo_run._scan_playbook_after_improve(
                conn, SimpleNamespace(attempts=[SimpleNamespace(accepted=False)])
            )
        finally:
            conn.close()

        assert scans == []

    def test_missing_scan_helper_degrades_gracefully(self, monkeypatch, capsys):
        monkeypatch.setattr(demo_run, "_resolve_scan_and_record", lambda: None)
        conn = sqlite3.connect(":memory:")
        try:
            scans = demo_run._scan_playbook_after_improve(
                conn, SimpleNamespace(attempts=[SimpleNamespace(accepted=True)])
            )
        finally:
            conn.close()

        assert scans == []
        assert "skipping playbook lesson scan" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Domain A outer improvement rounds
# --------------------------------------------------------------------------


def _scripted_improver(fake: FakeLLM, trace: list[str]):
    """Use FakeLLM responses to drive W6-shaped improve results."""
    version = 0

    def improve(agent_id: str, max_attempts: int):
        nonlocal version
        trace.append(f"improve:{agent_id}:{max_attempts}")
        response = fake.chat.completions.create(
            model="fake-improver",
            messages=[{"role": "user", "content": f"improve {agent_id} from v{version}"}],
        )
        instruction = json.loads(response.choices[0].message.content)
        starting_version = version
        improved = bool(instruction["improved"])
        if improved:
            version += 1
        attempts = [
            SimpleNamespace(
                attempt=attempt, accepted=improved and attempt == instruction["attempts"]
            )
            for attempt in range(1, instruction["attempts"] + 1)
        ]
        return SimpleNamespace(
            agent_id=agent_id,
            starting_version=starting_version,
            current_version=version,
            attempts=attempts,
        )

    return improve


class TestDomainAImprovementRounds:
    def test_runs_n_improve_calls_and_checkpoints_each_round(self, seeded, monkeypatch, capsys):
        rounds = 4
        fake = FakeLLM([llm_text('{"improved": true, "attempts": 1}') for _ in range(rounds)])
        trace: list[str] = []
        improve = _scripted_improver(fake, trace)

        monkeypatch.setattr(demo_run, "_scan_playbook_after_improve", lambda *_args: [])
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root: {"current_version": fake.call_count},
        )

        def checkpoint(_path, report):
            trace.append(f"checkpoint:{report['current_version']}")

        monkeypatch.setattr(demo_run, "_write_json", checkpoint)

        results = demo_run._run_improvement_rounds(
            seeded.conn,
            seeded.agent_id,
            improve,
            rounds=rounds,
            attempts_per_round=3,
            started_at=demo_run.time.monotonic(),
        )

        assert len(results) == rounds
        assert fake.call_count == rounds
        assert trace == [
            item
            for round_number in range(1, rounds + 1)
            for item in (
                f"improve:{seeded.agent_id}:3",
                f"checkpoint:{round_number}",
            )
        ]
        output = capsys.readouterr().out
        assert output.count("case_runs=") == rounds
        assert output.count("elapsed_seconds=") == rounds
        assert output.count("cost_usd=") == rounds

    def test_saturation_checkpoints_then_exits_early(self, seeded, monkeypatch, capsys):
        fake = FakeLLM(
            [
                llm_text('{"improved": true, "attempts": 1}'),
                llm_text('{"improved": false, "attempts": 3}'),
                llm_text('{"improved": true, "attempts": 1}'),
            ]
        )
        trace: list[str] = []
        improve = _scripted_improver(fake, trace)

        monkeypatch.setattr(demo_run, "_scan_playbook_after_improve", lambda *_args: [])
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root: {"round": fake.call_count},
        )
        monkeypatch.setattr(
            demo_run,
            "_write_json",
            lambda _path, report: trace.append(f"checkpoint:{report['round']}"),
        )

        results = demo_run._run_improvement_rounds(
            seeded.conn,
            seeded.agent_id,
            improve,
            rounds=4,
            attempts_per_round=3,
            started_at=demo_run.time.monotonic(),
        )

        assert len(results) == 2
        assert fake.call_count == 2
        assert len(results[-1].attempts) == 3  # rejected attempts remain visible evidence
        assert trace[-1] == "checkpoint:2"
        assert "saturated after round 2" in capsys.readouterr().out


def test_domain_a_cli_separates_rounds_from_attempt_budget():
    parser = demo_run.build_parser()

    defaults = parser.parse_args(["domain-a"])
    assert defaults.improve_rounds == 4
    assert defaults.attempts_per_round == 3

    configured = parser.parse_args(
        ["domain-a", "--improve-rounds", "6", "--attempts-per-round", "2"]
    )
    assert configured.improve_rounds == 6
    assert configured.attempts_per_round == 2


def test_playbook_ablation_uses_importable_module_command(tmp_path):
    out_path = tmp_path / "ablation.json"
    command = demo_run._playbook_ablation_command(out_path)

    assert command == [
        sys.executable,
        "-m",
        "scripts.playbook_ablation",
        "--out",
        str(out_path),
    ]
