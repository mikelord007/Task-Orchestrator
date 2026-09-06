from __future__ import annotations

from pathlib import Path

from backend.architect.evaluators import list_evaluators

REAL_EVALUATORS_ROOT = Path(__file__).resolve().parents[3] / "evaluators"


def test_list_evaluators_reads_the_synthetic_fixture(evaluator_dir):
    result = list_evaluators(evaluator_dir)
    assert len(result) == 1
    entry = result[0]
    assert entry["evaluator_id"] == "widget_triage"
    assert entry["domain"] == "widget_triage"
    assert "Given an issue" in entry["description"]
    assert entry["case_counts"] == {"train": 2, "holdout": 1}


def test_list_evaluators_returns_empty_for_a_missing_directory(tmp_path):
    assert list_evaluators(tmp_path / "nope") == []


def test_list_evaluators_skips_a_directory_missing_readme_or_cases(tmp_path):
    base = tmp_path / "evaluators" / "broken"
    base.mkdir(parents=True)
    (base / "README.md").write_text("x", encoding="utf-8")
    # no cases.jsonl
    assert list_evaluators(tmp_path / "evaluators") == []


def test_list_evaluators_reads_the_real_github_triage_and_ticket_triage_suites():
    result = {entry["evaluator_id"]: entry for entry in list_evaluators(REAL_EVALUATORS_ROOT)}
    assert set(result) == {"github_triage", "ticket_triage"}

    github = result["github_triage"]
    assert github["domain"] == "github_triage"
    assert github["description"]
    assert sum(github["case_counts"].values()) == 60
    assert set(github["allowed_tools"]) == {
        "github_get_issue_context",
        "github_search_similar_issues",
        "github_get_label_taxonomy",
        "github_find_component_owners",
    }

    ticket = result["ticket_triage"]
    assert ticket["domain"] == "ticket_triage"
    assert sum(ticket["case_counts"].values()) == 50
    assert set(ticket["allowed_tools"]) >= {"regex_extract", "json_validate"}
