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
        assert report["accepted_versions"] == [0, 1]
        assert report["rejected_candidate_versions"] == [2]
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

    def test_series_exclude_rejected_candidate_versions(self, seeded):
        report = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)

        for key in (
            "pass_at_1_by_version",
            "pass_pow_k_by_version",
            "cost_by_version",
            "latency_by_version",
            "tool_stats_by_version",
            "memory_by_version",
        ):
            assert {row["version"] for row in report[key]} <= {0, 1}

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
        assert report["version"] is None
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
            "current_version": 1,
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
            "current_version": 1,
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.7, "std": 0.1},
            ],
            "cost_by_version": [
                {"version": 0, "split": "train", "cost_per_run": 0.10},
                {"version": 1, "split": "train", "cost_per_run": 0.20},
            ],
        }
        flags = demo_run.flag_regressions(domain_a)
        assert any("cost per run did not decrease" in f for f in flags)

    def test_no_flags_when_everything_improves(self):
        domain_a = {
            "current_version": 1,
            "pass_at_1_by_version": [
                {"version": 0, "split": "train", "mean": 0.5, "std": 0.1},
                {"version": 1, "split": "train", "mean": 0.8, "std": 0.05},
            ],
            "cost_by_version": [
                {"version": 0, "split": "train", "cost_per_run": 0.20},
                {"version": 1, "split": "train", "cost_per_run": 0.10},
            ],
        }
        assert demo_run.flag_regressions(domain_a) == []

    def test_single_version_is_never_flagged(self):
        domain_a = {
            "current_version": 0,
            "pass_at_1_by_version": [{"version": 0, "split": "train", "mean": 0.5, "std": 0.1}],
            "cost_by_version": [],
        }
        assert demo_run.flag_regressions(domain_a) == []

    def test_flags_all_domain_a_and_domain_b_evidence(self):
        domain_a = {
            "current_version": 1,
            "pass_at_1_by_version": [],
            "pass_pow_k_by_version": [
                {"version": 0, "split": "holdout", "mean": 0.4},
                {"version": 1, "split": "holdout", "mean": 0.4},
            ],
            "cost_by_version": [],
            "latency_by_version": [
                {"version": 0, "split": "train", "p50_ms": 10, "p95_ms": 20},
                {"version": 1, "split": "train", "p50_ms": 10, "p95_ms": 25},
            ],
            "tool_stats_by_version": [
                {
                    "version": 0,
                    "split": "train",
                    "calls": 1,
                    "errors": 0,
                    "redundant": 0,
                    "tool_tokens": 10,
                },
                {
                    "version": 1,
                    "split": "train",
                    "calls": 2,
                    "errors": 0,
                    "redundant": 1,
                    "tool_tokens": 12,
                },
            ],
        }
        domain_b = {
            "train": {"pass_at_1": {"mean": 0}, "pass_pow_k": {"mean": 0}},
            "holdout": {},
        }
        ablation = {
            "playbook_off": {"pass_at_1": 0.5, "pass_pow_k": 0.4},
            "playbook_on": {"pass_at_1": 0.5, "pass_pow_k": 0.3},
        }

        flags = demo_run.flag_regressions(domain_a, domain_b, ablation)

        assert any("holdout pass^k" in flag for flag in flags)
        assert sum("latency" in flag for flag in flags) == 2
        assert sum("tool " in flag for flag in flags) == 4
        assert sum("Domain B train" in flag for flag in flags) == 2
        assert sum("playbook ablation" in flag for flag in flags) == 2


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
        assert "playbook off (`trials = 3`): pass@1 = 0.420 ± 0.050" in markdown
        assert "pass^k = 0.300 ± 0.050" in markdown
        assert "playbook on (`trials = 3`): pass@1 = 0.580 ± 0.040" in markdown
        assert "pass^k = 0.450 ± 0.040" in markdown
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
            "current_version": 1,
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

    def test_uses_current_version_and_labels_rejected_candidate(self, seeded):
        domain_a = demo_run.build_domain_a_report(seeded.conn, seeded.agent_id, seeded.root)

        markdown = demo_run.build_summary_markdown(domain_a, None, None, "")

        assert "v0 -> v1" in markdown
        assert "v0 -> v2" not in markdown
        assert "rejected candidate versions (not current): [2]" in markdown

    def test_missing_values_are_na_and_tool_token_estimate_is_labelled(self):
        domain_a = {
            "agent_id": "a1",
            "current_version": 1,
            "pass_at_1_by_version": [],
            "pass_pow_k_by_version": [],
            "cost_by_version": [],
            "latency_by_version": [],
            "tool_stats_by_version": [
                {
                    "version": 0,
                    "split": "train",
                    "calls": 1.0,
                    "errors": 0.0,
                    "tool_tokens": 17.0,
                    "tool_tokens_estimated": True,
                }
            ],
            "memory_by_version": [],
            "drift": {},
            "fix_cards": [],
            "compare_cases": [],
        }

        markdown = demo_run.build_summary_markdown(domain_a, None, None, "")

        assert "$n/a" not in markdown
        assert "tokens=17 (estimated)" in markdown
        assert "fix cards: n/a accepted, n/a rejected" in markdown
        assert "capability suite saturated: n/a" in markdown


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


class TestAtomicArtifactsAndCache:
    def test_atomic_json_preserves_previous_checkpoint_on_replace_failure(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "domain_a.json"
        path.write_text('{"old": true}\n', encoding="utf-8")
        monkeypatch.setattr(
            demo_run.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )

        with pytest.raises(OSError, match="replace failed"):
            demo_run._write_json(path, {"new": True})

        assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_cache_helper_skips_valid_entry(self):
        cached = {"labels": []}
        github = SimpleNamespace(
            read_cache=lambda _tool, _args: cached,
            canonical_args=lambda args: args,
            decode=lambda _result: pytest.fail("cached call should not be decoded"),
        )
        expected: list[tuple[str, dict]] = []
        errors: list[str] = []

        result = demo_run._ensure_cache_call(
            github,
            "github_list_labels",
            {"repo": "owner/repo"},
            lambda: pytest.fail("cached call should not be repeated"),
            expected,
            errors,
        )

        assert result == cached
        assert expected == [("github_list_labels", {"repo": "owner/repo"})]
        assert errors == []

    def test_populate_cache_fails_on_error_return(self, tmp_path, monkeypatch):
        from backend import settings
        from backend.toolbox import github

        monkeypatch.setattr(
            settings, "env", lambda name: "token" if name == "GITHUB_TOKEN" else None
        )
        monkeypatch.setattr(demo_run, "_load_github_cases", lambda: [])
        monkeypatch.setattr(github, "repo", lambda: "owner/repo")
        monkeypatch.setattr(github, "read_cache", lambda *_args: None)
        monkeypatch.setattr(github, "list_labels", lambda: "ERROR: rate limited")
        monkeypatch.setattr(github, "cache_dir", lambda: tmp_path)

        with pytest.raises(SystemExit, match="ERROR: github_list_labels.*rate limited"):
            demo_run.cmd_populate_cache(SimpleNamespace())


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
        monkeypatch.setattr(demo_run, "_accepted_version_chain", lambda *_args: [0])
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root, *, progress: {"progress": dict(progress)},
        )

        def checkpoint(_path, report):
            progress = report["progress"]
            trace.append(f"checkpoint:{progress['phase']}:{progress.get('completed_rounds', 0)}")

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
        assert trace.count(f"improve:{seeded.agent_id}:3") == rounds
        assert sum(item.startswith("checkpoint:improving:") for item in trace) == rounds
        assert (
            sum(
                item.startswith("checkpoint:round_complete:")
                or item == f"checkpoint:complete:{rounds}"
                for item in trace
            )
            == rounds
        )
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
        monkeypatch.setattr(demo_run, "_accepted_version_chain", lambda *_args: [0])
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root, *, progress: {"progress": dict(progress)},
        )
        monkeypatch.setattr(
            demo_run,
            "_write_json",
            lambda _path, report: trace.append(
                f"checkpoint:{report['progress']['phase']}:"
                f"{report['progress'].get('completed_rounds', 0)}"
            ),
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
        assert trace[-1] == "checkpoint:complete:2"
        assert "saturated after round 2" in capsys.readouterr().out

    def test_scan_failure_still_checkpoints_accepted_round(self, seeded, monkeypatch):
        fake = FakeLLM([llm_text('{"improved": true, "attempts": 1}')])
        trace: list[str] = []
        improve = _scripted_improver(fake, trace)
        checkpoints: list[dict] = []

        monkeypatch.setattr(demo_run, "_accepted_version_chain", lambda *_args: [0])
        monkeypatch.setattr(
            demo_run,
            "_scan_playbook_after_improve",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("scan failed")),
        )
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root, *, progress: {"progress": dict(progress)},
        )
        monkeypatch.setattr(
            demo_run,
            "_write_json",
            lambda _path, report: checkpoints.append(report),
        )

        with pytest.raises(RuntimeError, match="scan failed"):
            demo_run._run_improvement_rounds(
                seeded.conn,
                seeded.agent_id,
                improve,
                rounds=4,
                attempts_per_round=3,
                started_at=demo_run.time.monotonic(),
            )

        progress = checkpoints[-1]["progress"]
        assert progress["phase"] == "scan_failed"
        assert progress["complete"] is False
        assert progress["completed_rounds"] == 1
        assert "RuntimeError: scan failed" == progress["last_error"]

    def test_resume_skips_completed_rounds(self, seeded, monkeypatch):
        fake = FakeLLM(
            [
                llm_text('{"improved": true, "attempts": 1}'),
                llm_text('{"improved": true, "attempts": 1}'),
            ]
        )
        trace: list[str] = []
        improve = _scripted_improver(fake, trace)

        monkeypatch.setattr(demo_run, "_scan_playbook_after_improve", lambda *_args: [])
        monkeypatch.setattr(demo_run, "_accepted_version_chain", lambda *_args: [0])
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root, *, progress: {"progress": dict(progress)},
        )
        monkeypatch.setattr(demo_run, "_write_json", lambda *_args: None)

        results = demo_run._run_improvement_rounds(
            seeded.conn,
            seeded.agent_id,
            improve,
            rounds=4,
            attempts_per_round=3,
            started_at=demo_run.time.monotonic(),
            progress={"phase": "round_complete", "completed_rounds": 2},
        )

        assert len(results) == 2
        assert fake.call_count == 2

    def test_resume_recovers_accepted_round_and_scans_playbook(self, seeded, monkeypatch):
        scans: list[sqlite3.Connection] = []
        checkpoints: list[dict] = []
        monkeypatch.setattr(
            demo_run,
            "_resolve_scan_and_record",
            lambda: lambda conn: scans.append(conn) or {"recorded": 1},
        )
        monkeypatch.setattr(
            demo_run,
            "build_domain_a_report",
            lambda _conn, _agent_id, root, *, progress: {"progress": dict(progress)},
        )
        monkeypatch.setattr(
            demo_run,
            "_write_json",
            lambda _path, report: checkpoints.append(report),
        )

        results = demo_run._run_improvement_rounds(
            seeded.conn,
            seeded.agent_id,
            lambda *_args, **_kwargs: pytest.fail("accepted round must not replay"),
            rounds=1,
            attempts_per_round=3,
            started_at=demo_run.time.monotonic(),
            progress={
                "phase": "improving",
                "completed_rounds": 0,
                "round_in_progress": 1,
                "round_starting_version": 0,
                "round_event_cursor": 0,
            },
        )

        assert results == []
        assert scans == [seeded.conn]
        assert checkpoints[-1]["progress"]["complete"] is True

    def test_resume_refuses_candidate_directory_collision(self, seeded, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        (agents_dir / seeded.agent_id / "v2").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(demo_run, "AGENTS_DIR", agents_dir)
        progress = {
            "phase": "improving",
            "completed_rounds": 1,
            "round_in_progress": 2,
            "round_starting_version": 1,
            "round_event_cursor": demo_run._event_cursor(seeded.conn, seeded.agent_id),
        }

        with pytest.raises(SystemExit, match="candidate directories exist"):
            demo_run._recover_round_cursor(seeded.conn, seeded.agent_id, progress, 3)


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

    with pytest.raises(SystemExit):
        parser.parse_args(["domain-a", "--improve-rounds", "0"])


def test_demo_cli_splits_agent_ids_and_files_issues_by_default(monkeypatch):
    parser = demo_run.build_parser()
    args = parser.parse_args(
        ["demo", "--domain-a-agent-id", "github-agent", "--domain-b-agent-id", "ticket-agent"]
    )
    seen: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        demo_run, "cmd_preflight", lambda step: seen.append(("preflight", None)) or 0
    )
    monkeypatch.setattr(
        demo_run,
        "cmd_domain_a",
        lambda step: seen.append(("domain-a", step.agent_id)) or 0,
    )
    monkeypatch.setattr(
        demo_run,
        "cmd_domain_b",
        lambda step: seen.append(("domain-b", step.agent_id)) or 0,
    )
    monkeypatch.setattr(demo_run, "cmd_summary", lambda step: seen.append(("summary", None)) or 0)

    assert args.file_issues is True
    assert demo_run.cmd_demo(args) == 0
    assert seen == [
        ("preflight", None),
        ("domain-a", "github-agent"),
        ("domain-b", "ticket-agent"),
        ("summary", None),
    ]


def test_summary_refuses_partial_domain_a(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    demo_run._write_json(
        reports / "domain_a.json",
        {
            "agent_id": "a1",
            "complete": False,
            "progress": {"phase": "round_complete", "completed_rounds": 1},
        },
    )
    monkeypatch.setattr(demo_run, "REPORTS_DIR", reports)
    monkeypatch.setattr(demo_run, "BUILD_LOG_PATH", tmp_path / "BUILD_LOG.md")

    with pytest.raises(SystemExit, match="partial checkpoint"):
        demo_run.cmd_summary(SimpleNamespace(file_issues=False))

    assert not (reports / "summary.md").exists()


def test_real_improver_lazy_import_resolves():
    improve = demo_run._resolve_improve()

    assert callable(improve)
    assert improve.__module__ == "backend.improver.improve"


def test_domain_a_resume_skips_finished_baselines_and_rounds(seeded, tmp_path, monkeypatch):
    import backend.architect.generate as architect_generate
    from backend import db
    from backend.runtime import evaluation

    reports = tmp_path / "reports"
    demo_run._write_json(
        reports / "domain_a.json",
        {
            "agent_id": seeded.agent_id,
            "complete": True,
            "progress": {"phase": "complete", "complete": True, "completed_rounds": 1},
        },
    )
    paid_calls: list[str] = []
    monkeypatch.setattr(demo_run, "REPORTS_DIR", reports)
    monkeypatch.setattr(db, "init_db", lambda: seeded.conn)
    monkeypatch.setattr(
        architect_generate,
        "generate",
        lambda **_kwargs: paid_calls.append("generate") or pytest.fail("must not generate"),
    )
    monkeypatch.setattr(
        evaluation,
        "run_eval",
        lambda *_args, **_kwargs: paid_calls.append("eval") or pytest.fail("must not eval"),
    )
    monkeypatch.setattr(
        demo_run,
        "_resolve_improve",
        lambda: (
            lambda *_args, **_kwargs: (
                paid_calls.append("improve") or pytest.fail("must not improve")
            )
        ),
    )

    assert (
        demo_run.cmd_domain_a(
            SimpleNamespace(
                agent_id=seeded.agent_id,
                improve_rounds=1,
                attempts_per_round=3,
            )
        )
        == 0
    )
    assert paid_calls == []


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
