"""Build the `github_triage` evaluator from real closed issues on a GitHub repo.

Run once, commit the outputs. Nothing in the eval path imports this module; the
evaluator itself is fully offline and reads only the committed fixtures.

    python scripts/build_github_cases.py --repo Untrivial-ai/agent-orchestrator

Auth: `GITHUB_TOKEN` if set, otherwise the token from an authenticated `gh` CLI.

Outputs
-------
fixtures/github_triage/issues/<number>.json   raw issue + comments snapshot
evaluators/github_triage/cases.jsonl          the evaluator cases
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "fixtures" / "github_triage" / "issues"
CASES_PATH = REPO_ROOT / "evaluators" / "github_triage" / "cases.jsonl"
LIST_CACHE = REPO_ROOT / "fixtures" / "github_triage" / "_closed_issues_raw.json"

API = "https://api.github.com"
COMPONENT_RE = re.compile(r"^comp/")
PRIORITY_RE = re.compile(r"^P[0-9]+$")

# `duplicate of #12`, `dup of #12`, `closing as duplicate of #12`
DUPLICATE_RE = re.compile(
    r"(?:clos(?:ing|ed)\s+as\s+)?\bdup(?:licate)?\s+of\s+#(\d+)\b",
    re.IGNORECASE,
)

MIN_BODY_CHARS = 80
TARGET_CASES = 60
MIN_COMPONENTS = 4
TRAIN_FRACTION = 0.7

WINDOWS_RE = re.compile(r"\b(windows|conpty|powershell|win32|winpty)\b", re.IGNORECASE)
SHORT_BODY = 300
LONG_BODY = 3000

# `negative:*` cases (PLAN_ADDENDUM §F / addendum-deltas W4): issues where the
# correct answer is "nothing here", to catch an agent that invents an answer
# because the schema has a slot for one.
#
# `negative:no_priority` -- issues whose language reads as urgent while the
# maintainers set no priority at all. `NEGATIVE_TARGET` caps a genuinely larger
# pool (~24 candidates) down to the addendum's "~8".
URGENCY_RE = re.compile(
    r"\b(urgent|crash(?:es|ed|ing)?|broken|fails?|failing|failure|blocker|"
    r"blocking|critical|severe|regression|outage|hang(?:s|ing)?|freeze)\b",
    re.IGNORECASE,
)
NEGATIVE_TARGET = 8

# `negative:no_extra_labels` (issues whose only labels are `comp/*`, so the
# graded `labels` field is empty) does not occur anywhere in this repo's 1304
# closed issues, checked exhaustively (with and without a body-length floor):
# every `comp/*`-labelled issue here also carries a type label (`bug` on 47/60,
# `enhancement` on 13, `cloud` on 4, `needs-triage` on 1). There is nothing to
# tag and nothing to swap in from the wider corpus -- this is a real property
# of how this repo's maintainers triage, not a gap in the selection script, so
# no task is tagged `negative:no_extra_labels`.
#
# `negative:not_duplicate` -- issues whose body itself raises and resolves the
# duplicate/related-issue question (an explicit "duplicate search" section, or
# language distinguishing the issue from a similar-sounding prior one) while
# `duplicate_of` stays null. Unlike `no_priority`, this shows up as free text in
# the *body*, not as a label or a fixed phrase in a comment, so it cannot be
# swept up by a regex the way `no_priority`/`negative:no_priority` was; these five
# were located by reading the corpus and are pinned by id. If a future
# regeneration drops one of these issues from the selected 60, `apply_negative_tags`
# skips it rather than failing (see there).
NOT_DUPLICATE_IDS = {
    "gh-4420": "explicitly concludes 'not a duplicate' of a related issue (#3745)",
    "gh-4452": "body has a 'Duplicate search' section: searched issues/PRs, found none",
    "gh-4520": "body has a 'Duplicate Search / Related' section: no exact issue found",
    "gh-4639": "explicitly distinguishes itself from two related, similar-sounding issues",
    "gh-4908": "a 'sticky' failure that recurs on every task-creation attempt until restart",
}
NOT_DUPLICATE_TARGET_RANGE = (3, 5)


# --------------------------------------------------------------------------- auth


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - env
        raise SystemExit("No GITHUB_TOKEN and `gh auth token` failed; authenticate first.") from exc
    return out.stdout.strip()


def _get(path: str, token: str) -> Any:
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "task-orchestrator-build-github-cases",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"exhausted retries for {url}")


# ----------------------------------------------------------------------- fetching


def fetch_closed_issues(repo: str, token: str, max_pages: int = 40) -> list[dict]:
    """All closed issues (PRs excluded), newest first."""
    issues: list[dict] = []
    for page in range(1, max_pages + 1):
        batch = _get(
            f"/repos/{repo}/issues?state=closed&per_page=100&sort=created"
            f"&direction=desc&page={page}",
            token,
        )
        if not batch:
            break
        issues.extend(i for i in batch if "pull_request" not in i)
        print(f"  page {page}: {len(batch)} items, {len(issues)} issues so far")
        if len(batch) < 100:
            break
    return issues


def label_names(issue: dict) -> list[str]:
    return [
        lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels", []) or []
    ]


def components(names: list[str]) -> list[str]:
    return sorted(n for n in names if COMPONENT_RE.match(n))


def priority(names: list[str]) -> str:
    prios = sorted(n for n in names if PRIORITY_RE.match(n))
    return prios[0] if prios else "none"


def plain_labels(names: list[str]) -> list[str]:
    return sorted(n for n in names if not COMPONENT_RE.match(n) and not PRIORITY_RE.match(n))


# ------------------------------------------------------------------------ picking


def select(issues: list[dict]) -> list[dict]:
    """The newest `TARGET_CASES` eligible issues, widened to >= MIN_COMPONENTS."""
    eligible = [
        i
        for i in issues
        if components(label_names(i)) and len((i.get("body") or "").strip()) >= MIN_BODY_CHARS
    ]
    eligible.sort(key=lambda i: i["created_at"], reverse=True)

    chosen = eligible[:TARGET_CASES]
    seen = {c for i in chosen for c in components(label_names(i))}
    if len(seen) < MIN_COMPONENTS:
        # Reach further back for the newest issue of each missing component, and
        # drop an already well-represented one so the count stays at TARGET_CASES.
        for issue in eligible[TARGET_CASES:]:
            missing = set(components(label_names(issue))) - seen
            if not missing:
                continue
            counts: dict[str, int] = {}
            for candidate in chosen:
                for comp in components(label_names(candidate)):
                    counts[comp] = counts.get(comp, 0) + 1
            for idx in range(len(chosen) - 1, -1, -1):
                if all(counts[c] > 1 for c in components(label_names(chosen[idx]))):
                    chosen.pop(idx)
                    break
            else:
                continue
            chosen.append(issue)
            seen |= missing
            if len(seen) >= MIN_COMPONENTS:
                break
    chosen.sort(key=lambda i: i["created_at"])
    return chosen


def parse_duplicate_of(comments: list[dict]) -> int | None:
    for comment in comments:
        match = DUPLICATE_RE.search(comment.get("body") or "")
        if match:
            return int(match.group(1))
    return None


def build_tags(issue: dict, expected: dict) -> list[str]:
    body = issue.get("body") or ""
    tags = [f"comp:{c}" for c in expected["component"]]
    tags.append(f"prio:{expected['priority']}")
    if len(expected["component"]) > 1:
        tags.append("multi-component")
    if expected["priority"] == "none":
        tags.append("no-priority")
    if expected["duplicate_of"] is not None:
        tags.append("duplicate")
    if expected["assignee"]:
        tags.append("assigned")
    if WINDOWS_RE.search(body) or WINDOWS_RE.search(issue.get("title") or ""):
        tags.append("windows")
    if len(body) < SHORT_BODY:
        tags.append("short-body")
    if len(body) > LONG_BODY:
        tags.append("long-body")
    return sorted(dict.fromkeys(tags))


def is_negative_candidate(case: dict) -> bool:
    """Urgent-sounding language, but the maintainers set no priority at all.

    See the `NEGATIVE_TARGET` comment above: this is the real, present analogue
    of the addendum's "nothing here" negative-case examples, which do not occur
    in this corpus at all.
    """
    if case["expected"]["priority"] != "none":
        return False
    text = f"{case['input']['title'] or ''} {case['input']['body'] or ''}"
    return bool(URGENCY_RE.search(text))


def apply_negative_tags(cases: list[dict]) -> list[dict]:
    """Tag `negative:no_priority` and `negative:not_duplicate` cases.

    `negative:no_priority`: the `NEGATIVE_TARGET` oldest qualifying cases, capped
    and taken oldest-first (rather than every qualifying case) so the tag marks a
    deliberate, reproducible highlight set per the addendum's "~8" target instead
    of the ~24 cases that would otherwise qualify -- tagging all of them would
    just be relabelling the `no-priority` tag under a new name.

    `negative:not_duplicate`: the hand-picked `NOT_DUPLICATE_IDS` (see the comment
    there for why these can't be found by a keyword rule the way `no_priority`
    can). Skips an id if it is not among `cases` -- e.g. a future regeneration
    that no longer selects that issue -- rather than failing; `validate_evaluators.py`
    and the test suite check the resulting count still lands in
    `NOT_DUPLICATE_TARGET_RANGE`.
    """
    candidates = sorted(
        (c for c in cases if is_negative_candidate(c)),
        key=lambda c: c["input"]["created_at"],
    )
    for case in candidates[:NEGATIVE_TARGET]:
        case["tags"] = sorted(set(case["tags"]) | {"negative:no_priority"})

    by_id = {c["id"]: c for c in cases}
    for case_id in NOT_DUPLICATE_IDS:
        case = by_id.get(case_id)
        if case is None:
            continue
        assert case["expected"]["duplicate_of"] is None, (
            f"{case_id} is tagged negative:not_duplicate but has a duplicate_of"
        )
        case["tags"] = sorted(set(case["tags"]) | {"negative:not_duplicate"})
    return cases


def build_case(repo: str, issue: dict, comments: list[dict]) -> dict:
    names = label_names(issue)
    expected = {
        "labels": plain_labels(names),
        "component": components(names),
        "priority": priority(names),
        "assignee": (issue.get("assignee") or {}).get("login"),
        "duplicate_of": parse_duplicate_of(comments),
    }
    return {
        "id": f"gh-{issue['number']}",
        "split": "train",  # rewritten by the temporal split below
        "input": {
            "issue_number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body") or "",
            "author": (issue.get("user") or {}).get("login"),
            "created_at": issue["created_at"],
            "repo": repo,
        },
        "expected": expected,
        # PLAN_ADDENDUM §A: a concrete output that passes the grader. Every field
        # of `expected` here is part of the answer, so the two coincide; the field
        # exists so the validator can prove the task is winnable without knowing
        # which parts of `expected` a given domain treats as metadata.
        "reference_output": dict(expected),
        "tags": build_tags(issue, expected),
    }


def apply_temporal_split(cases: list[dict]) -> list[dict]:
    """Oldest 70% -> train, newest 30% -> holdout."""
    cases = sorted(cases, key=lambda c: (c["input"]["created_at"], c["input"]["issue_number"]))
    cut = round(len(cases) * TRAIN_FRACTION)
    for idx, case in enumerate(cases):
        case["split"] = "train" if idx < cut else "holdout"
    return cases


# --------------------------------------------------------------------------- main


def load_snapshots(snapshot_dir: Path = SNAPSHOT_DIR) -> list[dict]:
    """Every committed raw snapshot, oldest issue first."""
    snapshots = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(snapshot_dir.glob("*.json"))
    ]
    return sorted(snapshots, key=lambda s: s["issue"]["created_at"])


def cases_from_snapshots(snapshot_dir: Path = SNAPSHOT_DIR) -> list[dict]:
    """Rebuild the full case list from the committed snapshots alone.

    This is the offline reproducibility path: given `fixtures/github_triage/issues/`
    the corpus is derivable with no token and no network, so a later edit or
    re-close on GitHub can never move the ground truth underneath us.
    """
    snapshots = load_snapshots(snapshot_dir)
    cases = [build_case(s["repo"], s["issue"], s["comments"]) for s in snapshots]
    return apply_negative_tags(apply_temporal_split(cases))


def write_cases(cases: list[dict], cases_path: Path = CASES_PATH) -> None:
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(case, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the github_triage evaluator.")
    parser.add_argument("--repo", default="Untrivial-ai/agent-orchestrator")
    parser.add_argument(
        "--refresh-list",
        action="store_true",
        help="Re-fetch the closed-issue index instead of using the cached snapshot.",
    )
    args = parser.parse_args(argv)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Offline path: the snapshots are committed but the (gitignored, large) issue
    # index is not, which is what a fresh clone looks like. Rebuild from them.
    if not args.refresh_list and not LIST_CACHE.exists() and any(SNAPSHOT_DIR.glob("*.json")):
        cases = cases_from_snapshots()
        write_cases(cases)
        train = sum(1 for c in cases if c["split"] == "train")
        print(
            f"Rebuilt {CASES_PATH} from {len(cases)} committed snapshots"
            f" ({train} train / {len(cases) - train} holdout), no network used"
        )
        return 0

    token = _token()
    if LIST_CACHE.exists() and not args.refresh_list:
        print(f"Using cached issue index {LIST_CACHE}")
        issues = json.loads(LIST_CACHE.read_text(encoding="utf-8"))
    else:
        print(f"Fetching closed issues from {args.repo} ...")
        issues = fetch_closed_issues(args.repo, token)
        LIST_CACHE.write_text(json.dumps(issues), encoding="utf-8")
    print(f"{len(issues)} closed issues (PRs excluded)")

    chosen = select(issues)
    print(f"{len(chosen)} cases selected")

    cases = []
    for issue in chosen:
        number = issue["number"]
        snapshot_path = SNAPSHOT_DIR / f"{number}.json"
        if snapshot_path.exists():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        else:
            full = _get(f"/repos/{args.repo}/issues/{number}", token)
            comments = (
                _get(f"/repos/{args.repo}/issues/{number}/comments?per_page=100", token)
                if full.get("comments")
                else []
            )
            snapshot = {"repo": args.repo, "issue": full, "comments": comments}
            snapshot_path.write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"  snapshot {number} ({len(comments)} comments)")
        cases.append(build_case(args.repo, snapshot["issue"], snapshot["comments"]))

    cases = apply_negative_tags(apply_temporal_split(cases))
    write_cases(cases)

    train = sum(1 for c in cases if c["split"] == "train")
    comps: dict[str, int] = {}
    for case in cases:
        for comp in case["expected"]["component"]:
            comps[comp] = comps.get(comp, 0) + 1
    print(f"Wrote {CASES_PATH} ({train} train / {len(cases) - train} holdout)")
    print(f"Components: {comps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
