"""The cache-through data layer over the GitHub REST API for a single repo.

These are *internal* primitives, one per REST endpoint. They are not the tools
an agent sees -- per PLAN_ADDENDUM.md section F the agent-facing surface is the
four consolidated, task-shaped tools in ``toolbox.github_tools``, which compose
these. Keeping the endpoint layer separate means caching, retries, trimming and
redaction are implemented and tested once.

Design notes (they matter for the eval being deterministic):

* **Cache-through.** Every call is keyed by
  ``sha256(canonical_json({"tool": name, "args": args}))`` and stored at
  ``<cache_dir>/<key>.json`` as ``{"request", "response", "fetched_at"}``.
  Reads hit the cache first, so an eval run is offline, free and repeatable.
  ``GITHUB_LIVE=1`` bypasses the cache *read* but still writes it. A cache miss
  with no ``GITHUB_TOKEN`` returns an error string -- it never raises and never
  invents data.
* **Ground-truth redaction.** When ``contracts.context.current_case`` is set,
  the issue named by ``current_case["input"]["issue_number"]`` comes back with
  its human-applied triage fields removed and its comments hidden. Every other
  issue is returned in full -- that is what the agent learns the repo's
  conventions from. The cache always stores the unredacted response; redaction
  happens on read, so the same cache serves both eval and exploration.

Environment: ``GITHUB_REPO`` (default ``Untrivial-ai/agent-orchestrator``),
``GITHUB_TOKEN``, ``GITHUB_CACHE_DIR`` (default ``fixtures/github_cache``),
``GITHUB_LIVE``.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import err, ok, truncate

DEFAULT_REPO = "Untrivial-ai/agent-orchestrator"
DEFAULT_CACHE_DIR = "fixtures/github_cache"
API_ROOT = "https://api.github.com"

BODY_LIMIT = 4000
COMMENT_LIMIT = 2000
FILE_LIMIT = 20000
DEFAULT_PER_PAGE = 30
MAX_PER_PAGE = 100
MAX_ATTEMPTS = 3

#: Fields the maintainers apply by hand. These are the answer for the case
#: under evaluation, so they are stripped from that one issue.
REDACTED_ISSUE_FIELDS = (
    "labels",
    "assignees",
    "assignee",
    "milestone",
    "state",
    "closed_at",
    "state_reason",
)

HIDDEN_COMMENTS_NOTE = "comments hidden for the issue under evaluation"
HIDDEN_LINKED_NOTE = (
    "linked pull requests and commits hidden for the issue under evaluation"
)

# Used only until contracts.context exists (this module is built before Phase 0
# lands). _case_var() prefers the real contract once it is importable.
_fallback_current_case: contextvars.ContextVar = contextvars.ContextVar(
    "current_case", default=None
)


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def repo() -> str:
    return os.environ.get("GITHUB_REPO") or DEFAULT_REPO


def token() -> str | None:
    value = os.environ.get("GITHUB_TOKEN") or ""
    return value.strip() or None


def cache_dir() -> Path:
    return Path(os.environ.get("GITHUB_CACHE_DIR") or DEFAULT_CACHE_DIR)


def live() -> bool:
    return os.environ.get("GITHUB_LIVE", "").strip() in {"1", "true", "True", "yes"}


def _retry_base_seconds() -> float:
    try:
        return float(os.environ.get("GITHUB_RETRY_BASE_SECONDS", "1"))
    except ValueError:
        return 1.0


# --------------------------------------------------------------------------
# ground-truth redaction
# --------------------------------------------------------------------------


def _case_var() -> contextvars.ContextVar:
    """The ContextVar holding the evaluator case currently being run."""
    try:
        from contracts.context import current_case  # type: ignore

        if isinstance(current_case, contextvars.ContextVar):
            return current_case
    except (ImportError, AttributeError):  # pragma: no cover - until Phase 0 lands
        pass
    return _fallback_current_case


def evaluated_issue_number() -> int | None:
    """The issue number under evaluation right now, or None outside an eval."""
    try:
        case = _case_var().get()
    except LookupError:
        return None
    if not isinstance(case, dict):
        return None
    case_input = case.get("input")
    if not isinstance(case_input, dict):
        return None
    number = case_input.get("issue_number")
    if isinstance(number, bool) or not isinstance(number, (int, str)):
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _redact_issue(issue: dict, target: int) -> dict:
    if issue.get("number") != target:
        return issue
    redacted = {
        key: value for key, value in issue.items() if key not in REDACTED_ISSUE_FIELDS
    }
    redacted["redacted"] = True
    redacted["redaction_note"] = (
        "This is the issue under evaluation. The maintainer-applied fields "
        f"({', '.join(REDACTED_ISSUE_FIELDS)}) and its comments are withheld -- "
        "they are the answer. Infer them from other issues in this repo."
    )
    return redacted


def _redact(tool_name: str, args: dict, payload: Any) -> Any:
    target = evaluated_issue_number()
    if target is None or not isinstance(payload, dict):
        return payload

    if tool_name == "github_get_issue":
        return _redact_issue(payload, target)

    if tool_name in {"github_list_issues", "github_search_issues"}:
        issues = payload.get("issues")
        if isinstance(issues, list):
            payload = dict(payload)
            payload["issues"] = [
                _redact_issue(issue, target) if isinstance(issue, dict) else issue
                for issue in issues
            ]
        return payload

    if (
        tool_name == "github_list_issue_comments"
        and payload.get("issue_number") == target
    ):
        return {
            "issue_number": target,
            "count": 0,
            "comments": [],
            "note": HIDDEN_COMMENTS_NOTE,
        }

    if (
        tool_name == "github_get_issue_timeline"
        and payload.get("issue_number") == target
    ):
        return {
            "issue_number": target,
            "commit_shas": [],
            "references": [],
            "note": HIDDEN_LINKED_NOTE,
        }

    return payload


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def canonical_args(args: dict) -> dict:
    """Drop empty arguments so equivalent calls share one cache key."""
    return {
        key: value
        for key, value in args.items()
        if value is not None and value != "" and value != []
    }


def cache_key(tool_name: str, args: dict) -> str:
    request = {"tool": tool_name, "args": canonical_args(args)}
    blob = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_path(tool_name: str, args: dict) -> Path:
    return cache_dir() / f"{cache_key(tool_name, args)}.json"


def read_cache(tool_name: str, args: dict) -> Any | None:
    path = cache_path(tool_name, args)
    if not path.is_file():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or "response" not in entry:
        return None
    return entry["response"]


def write_cache(tool_name: str, args: dict, response: Any) -> None:
    path = cache_path(tool_name, args)
    entry = {
        "request": {"tool": tool_name, "args": canonical_args(args)},
        "response": response,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        # A read-only cache directory must not fail a run.
        pass


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class GitHubHTTPError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API returned {status}: {message}")
        self.status = status
        self.message = message


def _request(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "task-orchestrator-toolbox",
    }
    auth = token()
    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    last_error: GitHubHTTPError | None = None
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except (OSError, ValueError):  # pragma: no cover - body is best effort
                pass
            last_error = GitHubHTTPError(exc.code, body or exc.reason or "")
            if exc.code in (403, 429) and attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_base_seconds() * (2**attempt))
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise GitHubHTTPError(
                0, f"could not reach api.github.com ({exc.reason})"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GitHubHTTPError(
                0, f"GitHub returned a non-JSON body ({exc})"
            ) from exc
    raise last_error or GitHubHTTPError(0, "request failed")  # pragma: no cover


def _url(path: str, params: dict | None = None) -> str:
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)
    return f"{API_ROOT}{path}{query}"


# --------------------------------------------------------------------------
# cache-through dispatch
# --------------------------------------------------------------------------


def _cache_miss_error(tool_name: str, args: dict, reason: str) -> str:
    key = cache_key(tool_name, args)
    request = json.dumps(
        {"tool": tool_name, "args": canonical_args(args)}, sort_keys=True
    )
    return err(
        f"{tool_name}: cache miss for {request} (key {key[:12]}...) and {reason}. "
        f"No data was returned -- do not guess it. To populate the cache, run once "
        f"with GITHUB_TOKEN set and GITHUB_LIVE=1; the response is then written to "
        f"{cache_dir().as_posix()}/{key}.json."
    )


def call(tool_name: str, args: dict, fetch: Callable[[], Any]) -> str:
    """Cache-through execute + redact + JSON-encode. Never raises."""
    cached = read_cache(tool_name, args)

    if cached is not None and not live():
        return ok(_redact(tool_name, args, cached))

    if token() is None:
        if cached is not None:
            return ok(_redact(tool_name, args, cached))
        return _cache_miss_error(tool_name, args, "GITHUB_TOKEN is not set")

    try:
        payload = fetch()
    except GitHubHTTPError as exc:
        if cached is not None:
            return ok(_redact(tool_name, args, cached))
        return err(f"{tool_name}: {exc}")
    except Exception as exc:  # noqa: BLE001 -- a tool must never crash a run
        if cached is not None:
            return ok(_redact(tool_name, args, cached))
        return err(f"{tool_name}: unexpected failure ({exc.__class__.__name__}: {exc})")

    write_cache(tool_name, args, payload)
    return ok(_redact(tool_name, args, payload))


def decode(result: str) -> tuple[dict | list | None, str | None]:
    """Split a primitive's return into ``(payload, error)``.

    The consolidated tools compose several primitives. A primitive that misses
    the cache returns an error string; the consolidated tool must record that as
    a gap in its answer rather than propagate it as a failure or, worse, fill it
    in. ``(None, message)`` is a gap, ``(payload, None)`` is data.
    """
    if result.startswith("ERROR:"):
        return None, result[len("ERROR:") :].strip()
    try:
        return json.loads(result), None
    except json.JSONDecodeError as exc:  # pragma: no cover - primitives emit valid JSON
        return None, f"could not decode the response ({exc})"


# --------------------------------------------------------------------------
# response trimming
# --------------------------------------------------------------------------


def _login(value: Any) -> str | None:
    return value.get("login") if isinstance(value, dict) else None


def is_pull_request(item: dict) -> bool:
    return isinstance(item, dict) and "pull_request" in item


def trim_issue(issue: dict) -> dict:
    milestone = issue.get("milestone")
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "body": truncate(issue.get("body"), BODY_LIMIT),
        "labels": [
            label.get("name") if isinstance(label, dict) else label
            for label in (issue.get("labels") or [])
        ],
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "assignee": _login(issue.get("assignee")),
        "assignees": [
            login
            for login in (_login(a) for a in (issue.get("assignees") or []))
            if login
        ],
        "milestone": milestone.get("title") if isinstance(milestone, dict) else None,
        "author": _login(issue.get("user")),
        "comments": issue.get("comments"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "html_url": issue.get("html_url"),
    }


def trim_comment(comment: dict) -> dict:
    return {
        "author": _login(comment.get("user")),
        "created_at": comment.get("created_at"),
        "body": truncate(comment.get("body"), COMMENT_LIMIT),
    }


def trim_label(label: dict) -> dict:
    return {
        "name": label.get("name"),
        "description": label.get("description"),
        "color": label.get("color"),
    }


def trim_commit(commit: dict) -> dict:
    detail = commit.get("commit") or {}
    author = detail.get("author") or {}
    message = detail.get("message") or ""
    return {
        "sha": (commit.get("sha") or "")[:12],
        "message": message.split("\n", 1)[0][:200],
        "author": author.get("name"),
        "date": author.get("date"),
        "html_url": commit.get("html_url"),
    }


def _per_page(value: int | None) -> int:
    if not value:
        return DEFAULT_PER_PAGE
    return max(1, min(int(value), MAX_PER_PAGE))


# --------------------------------------------------------------------------
# the seven tools
# --------------------------------------------------------------------------


def list_issues(
    state: str = "open",
    labels: str | None = None,
    since: str | None = None,
    page: int = 1,
    per_page: int | None = None,
) -> str:
    args = {
        "repo": repo(),
        "state": state,
        "labels": labels,
        "since": since,
        "page": int(page or 1),
        "per_page": _per_page(per_page),
    }

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/issues",
                {
                    "state": args["state"],
                    "labels": args["labels"],
                    "since": args["since"],
                    "page": args["page"],
                    "per_page": args["per_page"],
                },
            )
        )
        items = [item for item in (raw or []) if not is_pull_request(item)]
        return {
            "repo": args["repo"],
            "state": args["state"],
            "page": args["page"],
            "count": len(items),
            "issues": [trim_issue(item) for item in items],
        }

    return call("github_list_issues", args, fetch)


def get_issue(number: int) -> str:
    args = {"repo": repo(), "number": int(number)}

    def fetch() -> dict:
        raw = _request(_url(f"/repos/{args['repo']}/issues/{args['number']}"))
        if is_pull_request(raw):
            return {
                "number": args["number"],
                "error": "that number is a pull request, not an issue",
            }
        return trim_issue(raw)

    return call("github_get_issue", args, fetch)


def list_issue_comments(number: int, per_page: int | None = None) -> str:
    args = {"repo": repo(), "number": int(number), "per_page": _per_page(per_page)}

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/issues/{args['number']}/comments",
                {"per_page": args["per_page"]},
            )
        )
        comments = [trim_comment(item) for item in (raw or [])]
        return {
            "issue_number": args["number"],
            "count": len(comments),
            "comments": comments,
        }

    return call("github_list_issue_comments", args, fetch)


def list_labels() -> str:
    args = {"repo": repo()}

    def fetch() -> dict:
        raw = _request(
            _url(f"/repos/{args['repo']}/labels", {"per_page": MAX_PER_PAGE})
        )
        labels = [trim_label(item) for item in (raw or [])]
        return {"repo": args["repo"], "count": len(labels), "labels": labels}

    return call("github_list_labels", args, fetch)


def search_issues(q: str, page: int = 1, per_page: int | None = None) -> str:
    args = {
        "repo": repo(),
        "q": q,
        "page": int(page or 1),
        "per_page": _per_page(per_page),
    }

    def fetch() -> dict:
        query = f"repo:{args['repo']} is:issue {args['q']}".strip()
        raw = _request(
            _url(
                "/search/issues",
                {"q": query, "page": args["page"], "per_page": args["per_page"]},
            )
        )
        items = [item for item in (raw.get("items") or []) if not is_pull_request(item)]
        return {
            "repo": args["repo"],
            "query": args["q"],
            "total_count": raw.get("total_count"),
            "count": len(items),
            "issues": [trim_issue(item) for item in items],
        }

    return call("github_search_issues", args, fetch)


def get_file(path: str, ref: str | None = None) -> str:
    args = {"repo": repo(), "path": path, "ref": ref}

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/contents/{urllib.parse.quote(args['path'])}",
                {"ref": args["ref"]},
            )
        )
        if isinstance(raw, list):
            return {
                "repo": args["repo"],
                "path": args["path"],
                "type": "dir",
                "entries": [
                    {"name": entry.get("name"), "type": entry.get("type")}
                    for entry in raw
                ],
            }
        content = raw.get("content") or ""
        if raw.get("encoding") == "base64":
            try:
                content = base64.b64decode(content).decode("utf-8", "replace")
            except (ValueError, TypeError):
                return {
                    "repo": args["repo"],
                    "path": args["path"],
                    "type": "binary",
                    "error": "file is binary and cannot be shown as text",
                }
        return {
            "repo": args["repo"],
            "path": args["path"],
            "type": "file",
            "size": raw.get("size"),
            "content": truncate(content, FILE_LIMIT),
        }

    return call("github_get_file", args, fetch)


def list_recent_commits(path: str | None = None, per_page: int | None = None) -> str:
    args = {"repo": repo(), "path": path, "per_page": _per_page(per_page)}

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/commits",
                {"path": args["path"], "per_page": args["per_page"]},
            )
        )
        commits = [trim_commit(item) for item in (raw or [])]
        return {
            "repo": args["repo"],
            "path": args["path"],
            "count": len(commits),
            "commits": commits,
        }

    return call("github_list_recent_commits", args, fetch)


def get_issue_timeline(number: int, per_page: int | None = None) -> str:
    """Cross-references and commit references on an issue.

    Used to answer "which PR or commit closed this, and what files did it
    touch" -- the strongest available evidence for a component decision.
    """
    args = {"repo": repo(), "number": int(number), "per_page": _per_page(per_page)}

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/issues/{args['number']}/timeline",
                {"per_page": args["per_page"]},
            )
        )
        commits: list[str] = []
        references: list[dict] = []
        for event in raw or []:
            if not isinstance(event, dict):
                continue
            name = event.get("event")
            if name in {"referenced", "closed"} and event.get("commit_id"):
                commits.append(event["commit_id"])
            elif name == "cross-referenced":
                source = (event.get("source") or {}).get("issue") or {}
                if source.get("number"):
                    references.append(
                        {
                            "number": source["number"],
                            "title": source.get("title"),
                            "is_pull_request": is_pull_request(source),
                            "state": source.get("state"),
                        }
                    )
        return {
            "issue_number": args["number"],
            "commit_shas": commits,
            "references": references,
        }

    return call("github_get_issue_timeline", args, fetch)


def get_commit(sha: str) -> str:
    """One commit with the paths it touched."""
    args = {"repo": repo(), "sha": str(sha)}

    def fetch() -> dict:
        raw = _request(_url(f"/repos/{args['repo']}/commits/{args['sha']}"))
        trimmed = trim_commit(raw)
        trimmed["files"] = [
            file.get("filename")
            for file in (raw.get("files") or [])
            if file.get("filename")
        ]
        return trimmed

    return call("github_get_commit", args, fetch)


def get_pull_files(number: int, per_page: int | None = None) -> str:
    """The paths a pull request touched."""
    args = {"repo": repo(), "number": int(number), "per_page": _per_page(per_page)}

    def fetch() -> dict:
        raw = _request(
            _url(
                f"/repos/{args['repo']}/pulls/{args['number']}/files",
                {"per_page": args["per_page"]},
            )
        )
        return {
            "pull_number": args["number"],
            "files": [
                file.get("filename") for file in (raw or []) if file.get("filename")
            ],
        }

    return call("github_get_pull_files", args, fetch)
