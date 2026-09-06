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


def test_keeps_current_metrics_null_when_summary_only_reports_evaluated_end():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)

    assert payload["demo_agent_id"] == "github-triage-itrs75"
    assert payload["domain"] == "github_triage"
    assert payload["current_version"] is None
    assert payload["trials"] == 3
    assert payload["fixes"] == {"accepted": 0, "rejected": 3}
    assert payload["tool_calls_per_task"] == {
        "split": "train",
        "before": {"version": 0, "value": 4.86},
        "after": {"version": None, "value": None},
    }


def test_counts_unique_sessions_and_prs_from_build_log_only():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)

    assert payload["ao_sessions"] == 2
    assert payload["pr_count"] == 2
    assert payload["provenance"]["semantics"]["ao_sessions"].startswith("unique worker")


def test_preserves_valid_zero_and_excludes_agent_ids_from_ablation():
    payload = export_landing_stats(SUMMARY, ABLATION, BUILD_LOG)

    observed = payload["provenance"]["unavailable_evidence"]["ablation"]
    assert observed["playbook_off"]["pass_at_1"] == 0.0
    assert observed["applied_lesson_ids"] == []
    assert "agent_ids" not in observed
    assert payload["ablation"] is None
    assert payload["pass_at_1_by_version"] == []
    assert payload["pass_pow_k_by_version"] == []
    assert payload["markers"] == []
    assert payload["chart"] is None


def test_missing_sources_and_ambiguous_current_remain_null():
    accepted_summary = SUMMARY.replace("0 accepted, 3 rejected", "1 accepted, 2 rejected")
    payload = export_landing_stats(accepted_summary, None, None)

    assert payload["current_version"] is None
    assert payload["tool_calls_per_task"]["after"] == {"version": None, "value": None}
    assert payload["ablation"] is None
    assert payload["ao_sessions"] is None
    assert payload["pr_count"] is None
    assert payload["provenance"]["sources"]["ablation"]["available"] is False


def test_ablation_is_exposed_only_when_applied_lessons_are_proven():
    ablation = json.loads(ABLATION)
    ablation["applied_lesson_ids"] = ["lesson-1"]

    payload = export_landing_stats(SUMMARY, json.dumps(ablation), BUILD_LOG)

    assert payload["ablation"] == {"with_lessons": 0.5, "without_lessons": 0.0}
    assert payload["provenance"]["unavailable_evidence"]["ablation"]["applied_lesson_ids"] == [
        "lesson-1"
    ]


def test_actual_current_version_is_corroboration_only():
    payload = export_landing_stats(
        SUMMARY,
        ABLATION,
        BUILD_LOG,
        json.dumps({"agent_id": "github-triage-itrs75", "current_version": 0}),
    )

    assert payload["current_version"] is None
    assert payload["provenance"]["corroborating_current_version"] == 0
    assert payload["provenance"]["sources"]["domain_a_corroboration"]["available"] is True
