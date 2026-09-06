from __future__ import annotations

import json

from scripts.export_landing_stats import export_landing_stats

SUMMARY = """\
# Task Orchestrator -- Evidence Summary

Every pass rate below is `pass@1 = mean ± std` and `pass^k = mean` at `trials = 3`.

## Domain A -- github_triage

Agent `github-triage-itrs75`, v0 -> v3.

- **train** pass@1: v0 0.563 ± 0.079 -> v3 0.611 ± 0.049; pass^k: v0 0.262 -> v3 0.333
- **holdout** pass@1: v0 0.370 ± 0.026 -> v3 n/a; pass^k: v0 0.056 -> v3 n/a

- tool calls/errors/tokens per task (train): v0 calls=4.86 errors=0.00 tokens=2845 -> v3 \
calls=4.56 errors=0.00 tokens=2621
- fix cards: 0 accepted, 3 rejected; regressions caught: 3

## Domain B -- ticket_triage
"""

BUILD_LOG = """\
# Build log

## Sessions

| session id | workstream | branch | PR | outcome |
|---|---|---|---|---|
| `task-orchestrator-7` | W1 | `one` | [#7](https://example.test/pull/7) | merged |
| `task-orchestrator-7` | W1b | `two` | [#11](https://example.test/pull/11) | merged |
| `task-orchestrator-8` | W2 | `three` | #7 | merged |
"""

ABLATION = json.dumps(
    {
        "domain": "ticket_triage",
        "trials": 3,
        "playbook_off": {"pass_at_1": 0.0, "pass_pow_k": 0.0, "std": 0.0},
        "playbook_on": {"pass_at_1": 0.5, "pass_pow_k": 0.25, "std": 0.1},
        "applied_lesson_ids": [],
        "agent_ids": {"playbook_off": "private-a", "playbook_on": "private-b"},
    }
)


def test_exports_current_as_baseline_when_every_fix_was_rejected():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)
    domain = payload["domain_a"]

    assert domain["agent_id"] == "github-triage-itrs75"
    assert domain["baseline_version"] == 0
    assert domain["current_version"] == 0
    assert domain["reported_end_version"] == 3
    assert domain["trials"] == 3
    assert domain["holdout"]["pass_at_1"] == {
        "before": {"mean": 0.370, "std": 0.026},
        "after": {"mean": 0.370, "std": 0.026},
    }
    assert domain["holdout"]["pass_pow_k"] == {
        "k": 3,
        "before": 0.056,
        "after": 0.056,
    }
    assert domain["fixes"] == {"accepted": 0, "rejected": 3}
    assert domain["tool_calls_per_task"] == {
        "split": "train",
        "before": 4.86,
        "after": 4.86,
        "reported_end": 4.56,
    }


def test_counts_unique_sessions_and_prs_from_build_log_only():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)

    assert payload["ao"] == {"sessions": 2, "prs": 2}
    assert payload["_provenance"]["semantics"]["ao_sessions"].startswith("unique worker")


def test_preserves_valid_zero_and_excludes_agent_ids_from_ablation():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)

    assert payload["ablation"]["playbook_off"]["pass_at_1"] == 0.0
    assert payload["ablation"]["applied_lesson_ids"] == []
    assert "agent_ids" not in payload["ablation"]
    assert payload["chart"] is None


def test_missing_sources_and_ambiguous_current_remain_null():
    accepted_summary = SUMMARY.replace("0 accepted, 3 rejected", "1 accepted, 2 rejected")
    payload = export_landing_stats(accepted_summary, None, None)

    assert payload["domain_a"]["current_version"] is None
    assert payload["domain_a"]["holdout"]["pass_at_1"]["after"] is None
    assert payload["domain_a"]["tool_calls_per_task"]["after"] is None
    assert payload["ablation"] is None
    assert payload["ao"] == {"sessions": None, "prs": None}
    assert payload["_provenance"]["sources"]["ablation"]["available"] is False
