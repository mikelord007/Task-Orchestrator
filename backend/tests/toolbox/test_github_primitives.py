"""The internal GitHub primitives: cache-through reads, key stability, redaction, and honest misses.

These are not agent-facing (see PLAN_ADDENDUM.md section F -- the four
consolidated tools in ``toolbox.github_tools`` are); they are the cache/HTTP
plumbing the composite tools are built on, tested once here so every composite
test can trust it.

Every test here runs with ``urlopen`` monkeypatched to raise, so a passing suite
is itself proof that the primitives are fully offline once the cache is
populated.
"""

from __future__ import annotations

import json

import pytest

from backend.toolbox import github

# Mirrors conftest.py; kept local so the module imports without a test package.
FIXTURE_REPO = "acme/widgets"
EVALUATED_ISSUE = 202


def load(result: str) -> dict:
    assert not result.startswith("ERROR:"), result
    return json.loads(result)


# ------------------------------------------------------------------ cache keys


def test_cache_key_is_stable_across_runs_and_key_order():
    # Pinned: if this changes, every committed fixture must be regenerated with
    # backend/tests/fixtures/build_github_cache.py.
    args = {"repo": "acme/widgets", "number": 101}
    assert (
        github.cache_key("github_get_issue", args)
        == "d8ff35e53c559e2a49339474183827d0f68f5e4ef7d798d93916e313c3be58ed"
    )
    reordered = {"number": 101, "repo": "acme/widgets"}
    assert github.cache_key("github_get_issue", reordered) == github.cache_key(
        "github_get_issue", args
    )


def test_cache_key_ignores_empty_arguments_but_not_real_ones():
    base = {"repo": "acme/widgets", "state": "closed"}
    assert github.cache_key("github_list_issues", {**base, "labels": None}) == github.cache_key(
        "github_list_issues", base
    )
    assert github.cache_key("github_list_issues", {**base, "labels": "bug"}) != github.cache_key(
        "github_list_issues", base
    )


def test_cache_key_separates_tools_with_identical_arguments():
    args = {"repo": "acme/widgets", "number": 101}
    assert github.cache_key("github_get_issue", args) != github.cache_key(
        "github_list_issue_comments", args
    )


def test_cache_entry_records_the_request_and_when_it_was_fetched(github_env, tmp_path):
    entry = json.loads(
        github.cache_path("github_get_issue", {"repo": FIXTURE_REPO, "number": 101}).read_text(
            encoding="utf-8"
        )
    )
    assert entry["request"] == {
        "tool": "github_get_issue",
        "args": {"repo": FIXTURE_REPO, "number": 101},
    }
    assert entry["fetched_at"]
    assert entry["response"]["number"] == 101


# --------------------------------------------------------------- cache reads


def test_every_primitive_answers_from_the_recorded_cache_without_network(github_env):
    assert load(github.get_issue(101))["title"].startswith("Terminal output garbled")
    assert load(github.list_issues(state="closed"))["count"] == 4
    assert load(github.list_issue_comments(101))["count"] == 2
    assert {label["name"] for label in load(github.list_labels())["labels"]} >= {
        "bug",
        "component:terminal",
    }
    assert load(github.search_issues("resize"))["total_count"] == 3
    assert "component:" in load(github.get_file("CONTRIBUTING.md"))["content"]
    assert load(github.list_recent_commits())["count"] == 2


def test_defaults_resolve_to_the_same_cache_entry_as_explicit_arguments(github_env):
    implicit = load(github.list_issue_comments(101))
    explicit = load(github.list_issue_comments(101, per_page=30))
    assert implicit == explicit


def test_live_mode_still_prefers_the_cache_when_there_is_no_token(github_env, monkeypatch):
    monkeypatch.setenv("GITHUB_LIVE", "1")
    assert load(github.get_issue(101))["number"] == 101


def test_a_populated_cache_is_reused_after_a_live_fetch_fails(github_env, monkeypatch):
    monkeypatch.setenv("GITHUB_LIVE", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    monkeypatch.setattr(
        github,
        "_request",
        lambda url: (_ for _ in ()).throw(github.GitHubHTTPError(503, "upstream is down")),
    )
    assert load(github.get_issue(101))["number"] == 101


# --------------------------------------------------------------- cache misses


def test_a_cache_miss_without_a_token_returns_an_explanatory_error(github_env):
    result = github.get_issue(999)
    assert result.startswith("ERROR:")
    assert "cache miss" in result
    assert "GITHUB_TOKEN is not set" in result
    assert "do not guess it" in result
    assert (
        github.cache_key("github_get_issue", {"repo": FIXTURE_REPO, "number": 999})[:12] in result
    )


def test_a_cache_miss_never_raises_for_any_primitive(github_env):
    misses = [
        github.get_issue(999),
        github.list_issues(state="open"),
        github.list_issue_comments(999),
        github.search_issues("nothing-matches-this"),
        github.get_file("does/not/exist.md"),
        github.list_recent_commits(path="src/"),
        github.get_issue_timeline(999),
        github.get_commit("deadbeef"),
        github.get_pull_files(999),
    ]
    assert all(result.startswith("ERROR:") for result in misses)


def test_a_failed_live_fetch_with_no_cache_reports_the_http_status(github_env, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    monkeypatch.setattr(
        github,
        "_request",
        lambda url: (_ for _ in ()).throw(github.GitHubHTTPError(404, "Not Found")),
    )
    result = github.get_issue(999)
    assert result.startswith("ERROR:")
    assert "404" in result


def test_a_live_fetch_writes_the_cache(github_env, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    monkeypatch.setattr(
        github,
        "_request",
        lambda url: {"number": 501, "title": "fresh", "labels": [{"name": "bug"}]},
    )
    assert load(github.get_issue(501))["title"] == "fresh"
    written = github.cache_path("github_get_issue", {"repo": FIXTURE_REPO, "number": 501})
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["response"]["labels"] == ["bug"]


# ---------------------------------------------------------------- redaction


def test_without_a_case_the_target_issue_is_returned_in_full(github_env):
    issue = load(github.get_issue(EVALUATED_ISSUE))
    assert issue["labels"] == ["bug", "platform:windows", "component:terminal"]
    assert issue["assignee"] == "dana"
    assert "redacted" not in issue


def test_get_issue_strips_the_ground_truth_for_the_issue_under_evaluation(
    under_evaluation,
):
    issue = load(github.get_issue(EVALUATED_ISSUE))
    for field in github.REDACTED_ISSUE_FIELDS:
        assert field not in issue, field
    assert issue["redacted"] is True
    assert issue["title"]
    assert issue["body"]
    assert issue["number"] == EVALUATED_ISSUE


def test_other_issues_keep_their_ground_truth_so_conventions_stay_learnable(
    under_evaluation,
):
    issue = load(github.get_issue(101))
    assert issue["labels"] == ["bug", "platform:windows", "component:terminal"]
    assert issue["assignee"] == "dana"
    assert issue["state"] == "closed"


@pytest.mark.parametrize(
    ("call", "args"),
    [
        (github.list_issues, {"state": "closed"}),
        (github.search_issues, ("resize",)),
    ],
)
def test_listings_redact_only_the_evaluated_issue(under_evaluation, call, args):
    if isinstance(args, dict):
        payload = load(call(**args))
    else:
        payload = load(call(*args))
    issues = {issue["number"]: issue for issue in payload["issues"]}
    assert EVALUATED_ISSUE in issues
    assert "labels" not in issues[EVALUATED_ISSUE]
    assert issues[EVALUATED_ISSUE]["redacted"] is True
    others = [issue for number, issue in issues.items() if number != EVALUATED_ISSUE]
    assert others
    assert all(issue["labels"] for issue in others)


def test_comments_on_the_evaluated_issue_are_hidden_with_a_note(under_evaluation):
    result = load(github.list_issue_comments(EVALUATED_ISSUE))
    assert result["comments"] == []
    assert result["count"] == 0
    assert result["note"] == github.HIDDEN_COMMENTS_NOTE


def test_comments_on_other_issues_are_untouched(under_evaluation):
    result = load(github.list_issue_comments(101))
    assert result["count"] == 2
    assert "note" not in result


def test_timeline_on_the_evaluated_issue_is_hidden_with_a_note(under_evaluation, monkeypatch):
    monkeypatch.setattr(
        github,
        "read_cache",
        lambda tool, args: (
            {
                "issue_number": EVALUATED_ISSUE,
                "commit_shas": ["abc123"],
                "references": [{"number": 5}],
            }
            if tool == "github_get_issue_timeline"
            else None
        ),
    )
    result = load(github.get_issue_timeline(EVALUATED_ISSUE))
    assert result["commit_shas"] == []
    assert result["references"] == []
    assert result["note"] == github.HIDDEN_LINKED_NOTE


def test_timeline_on_other_issues_is_untouched(under_evaluation, monkeypatch):
    real_payload = {
        "issue_number": 101,
        "commit_shas": ["abc123"],
        "references": [{"number": 5, "title": "x", "is_pull_request": False, "state": "closed"}],
    }
    monkeypatch.setattr(
        github,
        "read_cache",
        lambda tool, args: real_payload if tool == "github_get_issue_timeline" else None,
    )
    result = load(github.get_issue_timeline(101))
    assert result == real_payload


def test_redaction_leaves_the_cache_file_unredacted(under_evaluation):
    load(github.get_issue(EVALUATED_ISSUE))
    entry = json.loads(
        github.cache_path(
            "github_get_issue", {"repo": FIXTURE_REPO, "number": EVALUATED_ISSUE}
        ).read_text(encoding="utf-8")
    )
    assert entry["response"]["labels"] == [
        "bug",
        "platform:windows",
        "component:terminal",
    ]


def test_a_malformed_case_disables_redaction_rather_than_crashing(github_env):
    var = github._case_var()
    for bad_case in [
        {},
        {"input": None},
        {"input": {}},
        {"input": {"issue_number": None}},
        "nope",
    ]:
        token = var.set(bad_case)
        try:
            assert github.evaluated_issue_number() is None
            assert load(github.get_issue(EVALUATED_ISSUE))["labels"]
        finally:
            var.reset(token)


def test_a_string_issue_number_in_the_case_still_redacts(github_env):
    var = github._case_var()
    token = var.set({"input": {"issue_number": str(EVALUATED_ISSUE)}})
    try:
        assert "labels" not in load(github.get_issue(EVALUATED_ISSUE))
    finally:
        var.reset(token)


# --------------------------------------------------------------------- decode


def test_decode_splits_data_from_error():
    payload, error = github.decode(github.ok({"a": 1}))
    assert payload == {"a": 1}
    assert error is None

    payload, error = github.decode(github.err("boom"))
    assert payload is None
    assert error == "boom"


# ------------------------------------------------------- trimming and paging


def test_trim_issue_keeps_only_the_fields_an_agent_needs():
    raw = {
        "number": 7,
        "title": "t",
        "body": "b" * (github.BODY_LIMIT + 50),
        "labels": [{"name": "bug", "color": "ff0000", "id": 1}],
        "state": "closed",
        "assignee": {"login": "dana", "id": 2, "avatar_url": "..."},
        "assignees": [{"login": "dana"}, {"login": "sam"}],
        "milestone": {"title": "1.5", "id": 3},
        "user": {"login": "reporter"},
        "comments": 4,
        "html_url": "https://example.test/7",
        "node_id": "dropped",
        "reactions": {"+1": 99},
    }
    trimmed = github.trim_issue(raw)
    assert "node_id" not in trimmed and "reactions" not in trimmed
    assert trimmed["labels"] == ["bug"]
    assert trimmed["assignee"] == "dana"
    assert trimmed["assignees"] == ["dana", "sam"]
    assert trimmed["milestone"] == "1.5"
    assert trimmed["author"] == "reporter"
    assert "truncated" in trimmed["body"]
    assert len(trimmed["body"]) < len(raw["body"])


def test_pull_requests_are_excluded_from_issue_listings(github_env, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    monkeypatch.setattr(
        github,
        "_request",
        lambda url: [
            {"number": 1, "title": "an issue", "labels": []},
            {
                "number": 2,
                "title": "a PR",
                "labels": [],
                "pull_request": {"url": "..."},
            },
        ],
    )
    result = load(github.list_issues(state="all"))
    assert [issue["number"] for issue in result["issues"]] == [1]
    assert result["count"] == 1


def test_per_page_is_capped_at_one_hundred(github_env):
    assert github._per_page(None) == github.DEFAULT_PER_PAGE
    assert github._per_page(5000) == github.MAX_PER_PAGE
    assert github._per_page(50) == 50


def test_rate_limited_requests_are_retried_then_reported(github_env, monkeypatch):
    import urllib.error

    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    attempts = {"n": 0}

    def always_rate_limited(request, timeout=None):
        attempts["n"] += 1
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(github.urllib.request, "urlopen", always_rate_limited)
    with pytest.raises(github.GitHubHTTPError) as caught:
        github._request("https://api.github.com/x")
    assert attempts["n"] == github.MAX_ATTEMPTS
    assert caught.value.status == 429


def test_a_rate_limit_that_clears_on_retry_succeeds(github_env, monkeypatch):
    import io
    import urllib.error

    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    attempts = {"n": 0}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def flaky(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.HTTPError(request.full_url, 403, "rate limited", {}, None)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(github.urllib.request, "urlopen", flaky)
    assert github._request("https://api.github.com/x") == {"ok": True}
    assert attempts["n"] == 2


def test_non_rate_limit_errors_are_not_retried(github_env, monkeypatch):
    import urllib.error

    monkeypatch.setenv("GITHUB_TOKEN", "pretend-token")
    attempts = {"n": 0}

    def not_found(request, timeout=None):
        attempts["n"] += 1
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(github.urllib.request, "urlopen", not_found)
    with pytest.raises(github.GitHubHTTPError):
        github._request("https://api.github.com/x")
    assert attempts["n"] == 1


# ------------------------------------------------------------- argument errors


def test_primitives_do_not_validate_arguments_that_is_the_tool_layers_job(github_env):
    # The primitives are an internal seam; argument shape/range checks live in
    # backend/toolbox/github_tools/*.py, one layer up, where they can compose a
    # helpful error. A primitive given nonsense either raises (int() on a
    # non-numeric issue number) or, since GITHUB_TOKEN is unset, surfaces an
    # ordinary cache-miss error string -- it never fabricates data.
    with pytest.raises((TypeError, ValueError)):
        github.get_issue("not-a-number")
    assert github.list_issues(state="archived").startswith("ERROR:")
    assert github.get_file("").startswith("ERROR:")


def test_the_configured_repo_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    assert github.repo() == github.DEFAULT_REPO
    monkeypatch.setenv("GITHUB_REPO", "someone/else")
    assert github.repo() == "someone/else"
