"""The four agent-facing GitHub tools (PLAN_ADDENDUM.md section F).

Each composes the internal primitives tested in test_github_primitives.py.
Most tests here monkeypatch the primitives directly (github.get_issue,
github.list_issue_comments, ...) so the composition and redaction logic is
exercised without depending on more cache fixture files; a couple of
integration tests run one tool against the real recorded cache to prove the
whole path -- primitive cache reads through to composite output -- works
end to end.
"""

from __future__ import annotations

import json

import pytest
from toolbox import github
from toolbox.github_tools import (
    component_owners,
    issue_context,
    label_taxonomy,
    similar_issues,
)

# Mirrors conftest.py; kept local so the module imports without a test package.
FIXTURE_REPO = "acme/widgets"
EVALUATED_ISSUE = 202


def load(result: str) -> dict:
    assert not result.startswith("ERROR:"), result
    return json.loads(result)


# --------------------------------------------------------- github_get_issue_context


def test_issue_context_integrates_against_the_real_cache(github_env):
    result = load(issue_context.run({"issue_number": 101}))
    assert result["issue"]["title"].startswith("Terminal output garbled")
    assert result["comments"][0]["author"] == "dana"
    assert result["comments_truncated_count"] == 0
    assert result["response_format"] == "concise"


def test_issue_context_defaults_to_concise_and_shortens_comments(
    monkeypatch, github_env
):
    monkeypatch.setattr(
        github, "get_issue", lambda number: github.ok({"number": number, "title": "t"})
    )
    monkeypatch.setattr(
        github,
        "list_issue_comments",
        lambda number, per_page=None: github.ok(
            {
                "issue_number": number,
                "count": 1,
                "comments": [{"author": "a", "created_at": "t", "body": "x" * 1000}],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "get_issue_timeline",
        lambda number: github.ok(
            {"issue_number": number, "commit_shas": [], "references": []}
        ),
    )
    result = load(issue_context.run({"issue_number": 7}))
    assert result["response_format"] == "concise"
    assert len(result["comments"][0]["body"]) < 1000
    assert "truncated" in result["comments"][0]["body"]


def test_issue_context_detailed_mode_keeps_full_comments_and_exposes_ids(
    monkeypatch, github_env
):
    monkeypatch.setattr(
        github, "get_issue", lambda number: github.ok({"number": number})
    )
    monkeypatch.setattr(
        github,
        "list_issue_comments",
        lambda number, per_page=None: github.ok(
            {
                "issue_number": number,
                "count": 1,
                "comments": [{"author": "a", "body": "x" * 1000}],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "get_issue_timeline",
        lambda number: github.ok(
            {
                "issue_number": number,
                "commit_shas": ["abc123"],
                "references": [
                    {
                        "number": 9,
                        "title": "linked",
                        "is_pull_request": True,
                        "state": "open",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "get_commit",
        lambda sha: github.ok({"sha": sha, "message": "m", "files": ["a.py"]}),
    )
    result = load(issue_context.run({"issue_number": 7, "response_format": "detailed"}))
    assert len(result["comments"][0]["body"]) == 1000
    types = {item["type"] for item in result["linked"]}
    assert types == {"pull_request", "commit"}
    commit_entry = next(item for item in result["linked"] if item["type"] == "commit")
    assert commit_entry["sha"] == "abc123"
    assert commit_entry["files"] == ["a.py"]
    pr_entry = next(item for item in result["linked"] if item["type"] == "pull_request")
    assert pr_entry["number"] == 9


def test_issue_context_notes_truncation_and_how_to_narrow(monkeypatch, github_env):
    monkeypatch.setattr(
        github, "get_issue", lambda number: github.ok({"number": number})
    )
    many_comments = [{"author": f"u{i}", "body": "x"} for i in range(10)]
    monkeypatch.setattr(
        github,
        "list_issue_comments",
        lambda number, per_page=None: github.ok(
            {
                "issue_number": number,
                "count": len(many_comments),
                "comments": many_comments,
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "get_issue_timeline",
        lambda number: github.ok(
            {"issue_number": number, "commit_shas": [], "references": []}
        ),
    )
    result = load(issue_context.run({"issue_number": 7}))
    assert result["comments_truncated_count"] == 10 - issue_context.MAX_COMMENTS_CONCISE
    assert "response_format='detailed'" in result["comments_note"]


def test_issue_context_hides_ground_truth_and_comments_and_links_for_the_target(
    under_evaluation,
):
    result = load(issue_context.run({"issue_number": EVALUATED_ISSUE}))
    for field in github.REDACTED_ISSUE_FIELDS:
        assert field not in result["issue"]
    assert result["issue"]["redacted"] is True
    assert result["comments"] == []
    assert result["linked"] == []
    assert result["linked_note"] == github.HIDDEN_LINKED_NOTE


def test_issue_context_keeps_ground_truth_for_other_issues(under_evaluation):
    result = load(issue_context.run({"issue_number": 101}))
    assert result["issue"]["labels"]
    assert result["comments"]


def test_issue_context_reports_an_error_with_a_valid_call_example(github_env):
    result = issue_context.run({"issue_number": 0})
    assert result.startswith("ERROR:")
    assert "issue_number=" in result

    result = issue_context.run({"issue_number": 101, "response_format": "loud"})
    assert result.startswith("ERROR:")
    assert "concise" in result and "detailed" in result

    result = issue_context.run({"issue_number": 999999})
    assert result.startswith("ERROR:")
    assert "999999" in result


# ------------------------------------------------------ github_search_similar_issues


def test_similar_issues_integrates_against_the_real_cache(github_env):
    result = load(similar_issues.run({"query": "resize"}))
    assert result["total_count"] == 3
    assert {c["number"] for c in result["candidates"]} == {101, 140, 202}
    assert result["candidates"][0]["summary"]


def test_similar_issues_never_returns_the_evaluated_issue(under_evaluation):
    result = load(similar_issues.run({"query": "resize"}))
    numbers = {c["number"] for c in result["candidates"]}
    assert EVALUATED_ISSUE not in numbers
    assert numbers  # other matches still present


def test_similar_issues_notes_when_more_matched_than_the_limit(monkeypatch, github_env):
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {
                "query": q,
                "total_count": 5,
                "count": 2,
                "issues": [
                    {
                        "number": 1,
                        "title": "a",
                        "labels": [],
                        "state": "open",
                        "body": "line1\nline2\nline3",
                    },
                    {
                        "number": 2,
                        "title": "b",
                        "labels": [],
                        "state": "closed",
                        "body": None,
                    },
                ],
            }
        ),
    )
    result = load(similar_issues.run({"query": "x", "limit": 2}))
    assert result["count"] == 2
    assert "narrow the query" in result["note"]
    assert result["candidates"][0]["summary"] == "line1 line2"
    assert result["candidates"][1]["summary"] == ""


def test_similar_issues_validates_arguments_with_a_valid_call_example():
    assert similar_issues.run({"query": "  "}).startswith("ERROR:")
    result = similar_issues.run({"query": "x", "state": "archived"})
    assert result.startswith("ERROR:")
    assert "github_search_similar_issues(" in result
    assert similar_issues.run({}).startswith("ERROR:")


# -------------------------------------------------------- github_get_label_taxonomy


def test_label_taxonomy_reports_usage_and_examples(monkeypatch, github_env):
    monkeypatch.setattr(
        github,
        "list_labels",
        lambda: github.ok(
            {
                "repo": FIXTURE_REPO,
                "count": 1,
                "labels": [{"name": "bug", "description": "broken", "color": "red"}],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {
                "query": q,
                "total_count": 12,
                "count": 2,
                "issues": [
                    {"number": 1, "title": "first bug", "labels": ["bug"]},
                    {"number": 2, "title": "second bug", "labels": ["bug"]},
                ],
            }
        ),
    )
    result = load(label_taxonomy.run({}))
    assert result["count"] == 1
    entry = result["labels"][0]
    assert entry["usage_count"] == 12
    assert entry["example_titles"] == ["first bug", "second bug"]


def test_label_taxonomy_never_uses_the_evaluated_issue_as_an_example(
    monkeypatch, under_evaluation
):
    monkeypatch.setattr(
        github,
        "list_labels",
        lambda: github.ok(
            {
                "repo": FIXTURE_REPO,
                "count": 1,
                "labels": [{"name": "bug", "description": "d"}],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {
                "query": q,
                "total_count": 2,
                "count": 2,
                "issues": [
                    {
                        "number": EVALUATED_ISSUE,
                        "title": "the evaluated one",
                        "labels": ["bug"],
                    },
                    {"number": 5, "title": "a different one", "labels": ["bug"]},
                ],
            }
        ),
    )
    result = load(label_taxonomy.run({}))
    titles = result["labels"][0]["example_titles"]
    assert "the evaluated one" not in titles
    assert titles == ["a different one"]


def test_label_taxonomy_survives_labels_it_cannot_load(github_env):
    result = label_taxonomy.run({})
    # No network and no matching cache entry -> a clean error, never a crash
    # or a fabricated taxonomy.
    assert result.startswith("ERROR:") or json.loads(result)


# ---------------------------------------------------- github_find_component_owners


def test_component_owners_aggregates_commits_and_issues_per_term(
    monkeypatch, github_env
):
    monkeypatch.setattr(
        github,
        "list_recent_commits",
        lambda path=None, per_page=None: github.ok(
            {
                "repo": FIXTURE_REPO,
                "path": path,
                "count": 2,
                "commits": [{"author": "dana"}, {"author": "dana"}, {"author": "sam"}][
                    :2
                ],
            }
        ),
    )
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {
                "query": q,
                "total_count": 1,
                "count": 1,
                "issues": [
                    {
                        "number": 3,
                        "title": "t",
                        "labels": ["component:terminal"],
                        "assignee": "dana",
                    }
                ],
            }
        ),
    )
    result = load(component_owners.run({"paths_or_keywords": ["src/terminal"]}))
    entry = result["results"][0]
    assert entry["term"] == "src/terminal"
    assert entry["recent_authors"] == ["dana"]
    assert entry["labels_seen"] == ["component:terminal"]
    assert entry["assignees_seen"] == ["dana"]
    assert entry["evidence_issue_numbers"] == [3]


def test_component_owners_excludes_the_evaluated_issue_from_its_own_evidence(
    monkeypatch, under_evaluation
):
    monkeypatch.setattr(
        github,
        "list_recent_commits",
        lambda path=None, per_page=None: github.ok({"commits": []}),
    )
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {
                "query": q,
                "total_count": 1,
                "count": 1,
                "issues": [
                    {
                        "number": EVALUATED_ISSUE,
                        "title": "t",
                        "labels": ["component:terminal"],
                        "assignee": "dana",
                    }
                ],
            }
        ),
    )
    result = load(component_owners.run({"paths_or_keywords": ["terminal"]}))
    entry = result["results"][0]
    assert entry["labels_seen"] == []
    assert entry["assignees_seen"] == []
    assert entry["evidence_issue_numbers"] == []


def test_component_owners_deduplicates_and_caps_at_five_terms(monkeypatch, github_env):
    monkeypatch.setattr(
        github,
        "list_recent_commits",
        lambda path=None, per_page=None: github.ok({"commits": []}),
    )
    monkeypatch.setattr(
        github,
        "search_issues",
        lambda q, page=1, per_page=None: github.ok(
            {"total_count": 0, "count": 0, "issues": []}
        ),
    )
    terms = [f"term{i}" for i in range(8)]
    result = load(component_owners.run({"paths_or_keywords": terms}))
    assert [entry["term"] for entry in result["results"]] == terms[:5]
    assert "only the first 5" in result["note"]


def test_component_owners_validates_its_argument_shape():
    assert component_owners.run({}).startswith("ERROR:")
    assert component_owners.run({"paths_or_keywords": []}).startswith("ERROR:")
    assert component_owners.run({"paths_or_keywords": ["", "  "]}).startswith("ERROR:")
    assert component_owners.run({"paths_or_keywords": "not-a-list"}).startswith(
        "ERROR:"
    )


# --------------------------------------------------------------------- contracts


@pytest.mark.parametrize(
    "module", [issue_context, similar_issues, label_taxonomy, component_owners]
)
def test_every_composite_tool_exposes_the_tool_contract_and_never_raises(module):
    tool = module.TOOL
    assert set(tool) == {"name", "description", "input_schema"}
    assert tool["input_schema"]["type"] == "object"
    assert isinstance(module.run({}), str)
