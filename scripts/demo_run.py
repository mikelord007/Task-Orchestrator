"""End-to-end demo runner and evidence-report writer (W11 brief, PLAN_ADDENDUM.md).

    uv run --project backend python scripts/demo_run.py preflight
    uv run --project backend python scripts/demo_run.py populate-cache
    uv run --project backend python scripts/demo_run.py domain-a [--agent-id ID] [--max-attempts N]
    uv run --project backend python scripts/demo_run.py domain-b [--agent-id ID]
    uv run --project backend python scripts/demo_run.py summary [--file-issues]
    uv run --project backend python scripts/demo_run.py demo   # preflight -> domain-a -> domain-b
                                                                 # -> summary

Every number in ``reports/*.json`` and ``reports/summary.md`` is read back from
the ledger (``backend.ledger.metrics``) after a real run -- nothing here is
typed by hand (rule PLAN.md sec 2.8 / brief item "no fabricated numbers").

The improvement loop is still landing in a sibling branch while this one is
written, and the playbook scanner has an optional follow-up hook:

* ``backend.improver.improve`` (W6, ``ws/w6-improver``) -- imported lazily
  inside ``cmd_domain_a`` so this module (and its report-writer tests) stays
  importable before that package exists.
* ``scripts/playbook_ablation.py`` (W8) -- invoked as a subprocess from
  ``cmd_domain_b`` rather than imported, so its CLI is the integration
  boundary.
* ``backend.playbook.scan_and_record`` (W8b, ``ws/w8b-scan-hook``) -- imported
  lazily after an accepted improvement.  If W8b is absent, Domain A completes
  and reports that lesson scanning was skipped.

The report-writer functions (``build_domain_a_report``, ``select_compare_cases``,
``build_domain_b_report``, ``build_summary_markdown``, ``flag_regressions``,
``parse_build_log``) are pure functions of a ledger connection / dict, tested in
``scripts/tests/test_demo_run.py`` against W1's seeded ledger fixture with no
network and no dependency on W6/W8.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.ledger import metrics  # noqa: E402
from backend.ledger.query import agent_row  # noqa: E402
from backend.ledger.query import events as query_events  # noqa: E402

AGENTS_DIR = REPO_ROOT / "agents"
EVALUATORS_DIR = REPO_ROOT / "evaluators"
RUNS_DIR = REPO_ROOT / "runs"
REPORTS_DIR = REPO_ROOT / "reports"
GITHUB_CACHE_DIR = REPO_ROOT / "fixtures" / "github_cache"
GITHUB_CASES_PATH = EVALUATORS_DIR / "github_triage" / "cases.jsonl"
BUILD_LOG_PATH = REPO_ROOT / "BUILD_LOG.md"

DOMAIN_A_DOMAIN = "github_triage"
DOMAIN_A_EVALUATOR = "github_triage"
DOMAIN_A_GOAL = (
    "Triage an open GitHub issue on this repository the way its maintainers do: "
    "propose labels, component, priority, assignee, and duplicate-of, grounded in "
    "how similar issues were actually labelled and owned."
)
DEFAULT_MAX_ATTEMPTS = 4

REQUIRED_ENV = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL_STRONG",
    "LLM_MODEL_CHEAP",
    "GITHUB_TOKEN",
)

__all__ = [
    "build_domain_a_report",
    "build_domain_b_report",
    "build_summary_markdown",
    "flag_regressions",
    "parse_build_log",
    "select_compare_cases",
]


# --------------------------------------------------------------------------
# small shared helpers
# --------------------------------------------------------------------------


def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _fmt(value: float | int | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _pass_str(mean: float | None, std: float | None) -> str:
    if mean is None:
        return "n/a"
    if std is None:
        return f"{mean:.3f}"
    return f"{mean:.3f} ± {std:.3f}"


def _entry_by_version(series: list[dict[str, Any]], version: int) -> dict[str, Any] | None:
    for row in series:
        if row.get("version") == version:
            return row
    return None


def _entry_by_version_split(
    series: list[dict[str, Any]], version: int, split: str
) -> dict[str, Any] | None:
    for row in series:
        if row.get("version") == version and row.get("split") == split:
            return row
    return None


# --------------------------------------------------------------------------
# report writer: domain A (github_triage)
# --------------------------------------------------------------------------


def _all_case_ids(conn: sqlite3.Connection, agent_id: str) -> list[str]:
    """Every ``case_id`` this agent has ever been run on, first-seen order."""
    seen: set[str] = set()
    ids: list[str] = []
    for event in query_events(conn, kind="case_result", agent_id=agent_id):
        case_id = str(event.get("case_id"))
        if case_id not in seen:
            seen.add(case_id)
            ids.append(case_id)
    return ids


def select_compare_cases(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """The best ``limit`` tasks for "v0 was wrong, current is right" (sec G).

    Reuses ``metrics.compare`` (the same function ``GET /agents/{id}/compare``
    serves) so this never disagrees with the API about what "v0" or "current"
    means for a task. Ranked by how many rules fired on the current side --
    the clearest story for the demo is the one with the most visible memory
    doing the work.
    """
    row = agent_row(conn, agent_id)
    current_version = row.get("current_version") if row else None
    if not current_version:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for case_id in _all_case_ids(conn, agent_id):
        result = metrics.compare(conn, agent_id, case_id, root)
        v0, current = result.get("v0"), result.get("current")
        if not v0 or not current:
            continue
        if v0.get("passed") or not current.get("passed"):
            continue
        scored.append((len(current.get("rules_injected") or []), result))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in scored[:limit]]


def build_domain_a_report(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None
) -> dict[str, Any]:
    """``reports/domain_a.json`` (W11 brief item 3), built entirely from the ledger.

    Mostly a repackaging of ``metrics.insights`` (the same payload
    ``GET /insights/{id}`` serves) plus the pieces insights does not carry:
    the full fix-card list, accepted/rejected counts, and the three demo
    compare cases.
    """
    insights = metrics.insights(conn, agent_id, root)
    cards = metrics.fix_cards(conn, agent_id, root)
    accepted = sum(1 for card in cards if card.get("status") == "accepted")
    rejected = sum(1 for card in cards if card.get("status") == "rejected")
    return {
        "agent_id": agent_id,
        "domain": insights.get("domain"),
        "current_version": insights.get("current_version"),
        "trials": insights.get("trials"),
        "pass_at_1_by_version": insights["pass_at_1_by_version"],
        "pass_pow_k_by_version": insights["pass_pow_k_by_version"],
        "cost_by_version": insights["cost_by_version"],
        "latency_by_version": insights["latency_by_version"],
        "tool_stats_by_version": insights["tool_stats_by_version"],
        "memory_by_version": insights["memory_by_version"],
        "drift": insights["drift"],
        "fixes_by_lever": insights["fixes_by_lever"],
        "fixes_accepted": accepted,
        "fixes_rejected": rejected,
        "regressions_caught": insights["regressions_caught"],
        "graduated_count": insights["graduated_count"],
        "saturated": insights["saturated"],
        "flagged_tasks": insights["flagged_tasks"],
        "lessons_count": insights["lessons_count"],
        "markers": insights["markers"],
        "compare_cases": select_compare_cases(conn, agent_id, root),
        "fix_cards": cards,
    }


# --------------------------------------------------------------------------
# report writer: domain B (ticket_triage, v0 only -- no improve iterations, sec M)
# --------------------------------------------------------------------------


def build_domain_b_report(
    conn: sqlite3.Connection, agent_id: str, root: str | Path | None = None
) -> dict[str, Any]:
    """``reports/domain_b.json``: v0 train + holdout for the playbook-on agent.

    Domain B has no improve iterations (cut per PLAN_ADDENDUM.md sec M --
    ``scripts/playbook_ablation.py`` covers the on/off comparison instead), so
    this is a single version's numbers, not a version-over-version curve.
    """
    row = agent_row(conn, agent_id)
    version = row.get("current_version", 0) if row else 0
    report: dict[str, Any] = {
        "agent_id": agent_id,
        "domain": row.get("domain") if row else None,
        "version": version,
    }
    for split in ("train", "holdout"):
        report[split] = {
            "pass_at_1": metrics.pass_at_1(conn, agent_id, version, split),
            "pass_pow_k": metrics.pass_pow_k(conn, agent_id, version, split),
            "cost_per_run": metrics.cost_per_run(conn, agent_id, version, split),
            "latency": metrics.latency_percentiles(conn, agent_id, version, split),
            "tool_stats": metrics.tool_call_stats(conn, agent_id, version, split, root)[
                "aggregate"
            ],
        }
    return report


# --------------------------------------------------------------------------
# BUILD_LOG.md -> AO session / PR counts
# --------------------------------------------------------------------------

_SESSION_CELL_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|")
_PR_NUMBER_RE = re.compile(r"#(\d+)")


def parse_build_log(text: str) -> dict[str, Any]:
    """Distinct AO session ids and PR numbers from the ``## Sessions`` table.

    Deliberately tolerant of the exact column set (only "first cell is a
    backtick-quoted session id" and "some cell contains a `#123` PR link" are
    assumed) since every worker appends its own row to this table.
    """
    sessions: set[str] = set()
    prs: set[str] = set()
    in_sessions = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_sessions = stripped.startswith("## Sessions")
            continue
        if not in_sessions or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or set(cells[0]) <= {"-", " "}:
            continue
        match = _SESSION_CELL_RE.match(stripped)
        if match:
            sessions.add(match.group(1))
        for cell in cells:
            prs.update(_PR_NUMBER_RE.findall(cell))
    return {"session_count": len(sessions), "sessions": sorted(sessions), "pr_count": len(prs)}


# --------------------------------------------------------------------------
# flat/negative detection (brief: "report it as-is and open a GitHub issue")
# --------------------------------------------------------------------------


def flag_regressions(domain_a: dict[str, Any]) -> list[str]:
    """Plain-English notes for any headline number that did not improve v0->vN."""
    flags: list[str] = []
    versions = sorted({row["version"] for row in domain_a.get("pass_at_1_by_version", [])})
    if len(versions) < 2:
        return flags
    v0, v_n = versions[0], versions[-1]
    for split in ("train", "holdout"):
        before = _entry_by_version_split(domain_a["pass_at_1_by_version"], v0, split)
        after = _entry_by_version_split(domain_a["pass_at_1_by_version"], v_n, split)
        if before and after and before.get("mean") is not None and after.get("mean") is not None:
            if after["mean"] <= before["mean"]:
                flags.append(
                    f"{split} pass@1 did not improve v{v0}->v{v_n}: "
                    f"{before['mean']:.3f} -> {after['mean']:.3f}"
                )
    cost_before = _entry_by_version(domain_a.get("cost_by_version", []), v0)
    cost_after = _entry_by_version(domain_a.get("cost_by_version", []), v_n)
    if (
        cost_before
        and cost_after
        and cost_before.get("cost_per_run") is not None
        and cost_after.get("cost_per_run") is not None
        and cost_after["cost_per_run"] > cost_before["cost_per_run"]
    ):
        flags.append(
            f"cost per run increased v{v0}->v{v_n}: "
            f"${cost_before['cost_per_run']:.4f} -> ${cost_after['cost_per_run']:.4f}"
        )
    return flags


# --------------------------------------------------------------------------
# report writer: summary.md
# --------------------------------------------------------------------------


def _best_accepted_card(cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The card for the README/summary "here is the mechanism" section.

    Prefers an accepted ``memory`` fix (brief: "the best accepted memory
    fix"); falls back to the best-gaining accepted fix of any lever, then to
    None when nothing has been accepted yet.
    """
    accepted = [c for c in cards if c.get("status") == "accepted"]
    if not accepted:
        return None
    pool = [c for c in accepted if c.get("lever") == "memory"] or accepted

    def gain(card: dict[str, Any]) -> float:
        before = (card.get("before") or {}).get("pass_at_1")
        after = (card.get("after") or {}).get("pass_at_1")
        return after - before if before is not None and after is not None else -1.0

    return max(pool, key=gain)


def build_summary_markdown(
    domain_a: dict[str, Any],
    domain_b: dict[str, Any] | None,
    ablation: dict[str, Any] | None,
    build_log_text: str,
    *,
    generated_at: str | None = None,
) -> str:
    """``reports/summary.md`` (W11 brief item 5). Every number is read from the
    report dicts above, which are themselves read straight from the ledger."""
    lines: list[str] = []
    trials = domain_a.get("trials")
    lines.append("# Task Orchestrator -- Evidence Summary")
    lines.append("")
    lines.append(f"Generated {generated_at or datetime.now(UTC).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        f"Every pass rate below is `pass@1 = mean ± std` and `pass^k = mean` "
        f"at `trials = {trials}` (PLAN_ADDENDUM.md sec B/J)."
    )
    lines.append("")

    versions = sorted({row["version"] for row in domain_a.get("pass_at_1_by_version", [])})
    v0, v_n = (versions[0], versions[-1]) if versions else (0, 0)

    lines.append("## Domain A -- github_triage")
    lines.append("")
    lines.append(f"Agent `{domain_a.get('agent_id')}`, v{v0} -> v{v_n}.")
    lines.append("")
    for split in ("train", "holdout"):
        p1_before = _entry_by_version_split(domain_a["pass_at_1_by_version"], v0, split)
        p1_after = _entry_by_version_split(domain_a["pass_at_1_by_version"], v_n, split)
        pk_before = _entry_by_version_split(domain_a["pass_pow_k_by_version"], v0, split)
        pk_after = _entry_by_version_split(domain_a["pass_pow_k_by_version"], v_n, split)
        lines.append(
            f"- **{split}** pass@1: v{v0} "
            f"{_pass_str(p1_before and p1_before.get('mean'), p1_before and p1_before.get('std'))}"
            f" -> v{v_n} "
            f"{_pass_str(p1_after and p1_after.get('mean'), p1_after and p1_after.get('std'))}"
            f"; pass^k: v{v0} {_fmt(pk_before and pk_before.get('mean'))}"
            f" -> v{v_n} {_fmt(pk_after and pk_after.get('mean'))}"
        )
    lines.append("")

    cost_before = _entry_by_version(domain_a.get("cost_by_version", []), v0)
    cost_after = _entry_by_version(domain_a.get("cost_by_version", []), v_n)
    lat_before = _entry_by_version(domain_a.get("latency_by_version", []), v0)
    lat_after = _entry_by_version(domain_a.get("latency_by_version", []), v_n)
    lines.append(
        f"- cost per run: v{v0} ${_fmt(cost_before and cost_before.get('cost_per_run'), 4)}"
        f" -> v{v_n} ${_fmt(cost_after and cost_after.get('cost_per_run'), 4)}"
    )
    lines.append(
        f"- latency p50/p95: v{v0} "
        f"{_fmt(lat_before and lat_before.get('p50_ms'), 0)}/"
        f"{_fmt(lat_before and lat_before.get('p95_ms'), 0)} ms"
        f" -> v{v_n} "
        f"{_fmt(lat_after and lat_after.get('p50_ms'), 0)}/"
        f"{_fmt(lat_after and lat_after.get('p95_ms'), 0)} ms"
    )

    tool_before = _entry_by_version_split(domain_a.get("tool_stats_by_version", []), v0, "train")
    tool_after = _entry_by_version_split(domain_a.get("tool_stats_by_version", []), v_n, "train")
    lines.append(
        "- tool calls/errors/tokens per task (train): "
        f"v{v0} calls={_fmt(tool_before and tool_before.get('calls'), 2)} "
        f"errors={_fmt(tool_before and tool_before.get('errors'), 2)} "
        f"tokens={_fmt(tool_before and tool_before.get('tool_tokens'), 0)}"
        f" -> v{v_n} calls={_fmt(tool_after and tool_after.get('calls'), 2)} "
        f"errors={_fmt(tool_after and tool_after.get('errors'), 2)} "
        f"tokens={_fmt(tool_after and tool_after.get('tool_tokens'), 0)}"
    )
    lines.append(f"- fixes by lever: {json.dumps(domain_a.get('fixes_by_lever', {}))}")
    lines.append(
        f"- fix cards: {domain_a.get('fixes_accepted', 0)} accepted, "
        f"{domain_a.get('fixes_rejected', 0)} rejected; "
        f"regressions caught: {domain_a.get('regressions_caught', 0)}"
    )
    drift = domain_a.get("drift", {})
    lines.append(
        f"- drift by kind: {json.dumps(drift.get('count_by_kind', {}))}; "
        f"tokens saved: {drift.get('tokens_saved', 0)}; "
        f"cases recovered by nudge: {drift.get('cases_recovered_by_nudge', 0)}"
    )
    mem_rows = domain_a.get("memory_by_version", [])
    if mem_rows:
        first, last = mem_rows[0], mem_rows[-1]
        lines.append(
            f"- memory growth: v{first.get('version')} rules={first.get('rules')} "
            f"tool_notes={first.get('tool_notes')} -> v{last.get('version')} "
            f"rules={last.get('rules')} tool_notes={last.get('tool_notes')} "
            f"demotions={last.get('demotions')}"
        )
    lines.append(f"- graduated tasks: {domain_a.get('graduated_count', 0)}")
    lines.append(f"- capability suite saturated: {domain_a.get('saturated', False)}")
    lines.append(f"- lessons count (cross-agent playbook): {domain_a.get('lessons_count', 0)}")
    lines.append("")

    flags = flag_regressions(domain_a)
    if flags:
        lines.append(
            "**Flagged (flat or negative -- reported as-is, not massaged; "
            "a GitHub issue is opened for each when run with `--file-issues`):**"
        )
        for flag in flags:
            lines.append(f"- {flag}")
        lines.append("")

    lines.append("### Best accepted fix card (verbatim)")
    lines.append("")
    best_card = _best_accepted_card(domain_a.get("fix_cards", []))
    if best_card is not None:
        lines.append("```json")
        lines.append(json.dumps(best_card, indent=2))
        lines.append("```")
    else:
        lines.append("_no accepted fix card yet._")
    lines.append("")

    lines.append("### Compare cases: v0 wrong -> current right")
    lines.append("")
    compare_cases = domain_a.get("compare_cases", [])
    if compare_cases:
        for case in compare_cases:
            current = case.get("current") or {}
            lines.append(
                f"- **{case.get('case_id')}** (v0 -> v{current.get('version')}): "
                f"rules fired = {current.get('rules_injected')}, "
                f"tool calls v0={((case.get('v0') or {}).get('tool_calls'))} "
                f"-> v{current.get('version')}={current.get('tool_calls')}"
            )
    else:
        lines.append("_none found yet (need at least one accepted fix)._")
    lines.append("")

    lines.append("## Domain B -- ticket_triage")
    lines.append("")
    if domain_b:
        lines.append(
            f"Agent `{domain_b.get('agent_id')}` (playbook on), v{domain_b.get('version')}."
        )
        for split in ("train", "holdout"):
            stat = domain_b.get(split) or {}
            p1 = stat.get("pass_at_1") or {}
            pk = stat.get("pass_pow_k") or {}
            lines.append(
                f"- {split} pass@1: {_pass_str(p1.get('mean'), p1.get('std'))}; "
                f"pass^k: {_fmt(pk.get('mean'))}"
            )
    else:
        lines.append("_not run._")
    lines.append("")

    lines.append("### Playbook ablation (Domain B, playbook on vs off)")
    lines.append("")
    if ablation:
        off, on = ablation.get("playbook_off", {}), ablation.get("playbook_on", {})
        lines.append(
            f"- playbook off: pass@1 {_pass_str(off.get('pass_at_1'), off.get('std'))}, "
            f"pass^k {_fmt(off.get('pass_pow_k'))}"
        )
        lines.append(
            f"- playbook on:  pass@1 {_pass_str(on.get('pass_at_1'), on.get('std'))}, "
            f"pass^k {_fmt(on.get('pass_pow_k'))}"
        )
        lines.append(f"- applied lesson ids: {ablation.get('applied_lesson_ids', [])}")
    else:
        lines.append("_not run._")
    lines.append("")

    build_log = parse_build_log(build_log_text)
    lines.append("## AO usage")
    lines.append("")
    lines.append(f"- AO sessions: {build_log['session_count']}")
    lines.append(f"- PRs: {build_log['pr_count']}")
    lines.append("")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# populate-cache helpers
# --------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
    "when", "this", "that", "not", "no", "it", "be", "as", "at", "by", "from", "but",
}  # fmt: skip


def _top_keywords(title: str, limit: int = 5) -> list[str]:
    """A handful of distinctive words from an issue title, for component-owner lookups."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_/-]{2,}", title.lower())
    out: list[str] = []
    for word in words:
        if word in _STOPWORDS or word in out:
            continue
        out.append(word)
        if len(out) >= limit:
            break
    return out


def _load_github_cases() -> list[dict[str, Any]]:
    if not GITHUB_CASES_PATH.is_file():
        raise SystemExit(f"no evaluator cases at {GITHUB_CASES_PATH}")
    cases = []
    for line in GITHUB_CASES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


# --------------------------------------------------------------------------
# CLI commands
# --------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    from backend import llm
    from backend.settings import env

    print("Environment check:")
    missing = []
    for name in REQUIRED_ENV:
        present = bool(env(name))
        print(f"  {name}: {'present' if present else 'MISSING'}")
        if not present:
            missing.append(name)
    if missing:
        print(f"\nRefusing to run: missing {', '.join(missing)}. Set them in .env.")
        return 1

    api_url = (env("API_URL") or "http://localhost:8000").rstrip("/")
    try:
        import httpx

        response = httpx.get(f"{api_url}/healthz", timeout=5.0)
        response.raise_for_status()
        print(f"\n/healthz OK at {api_url}: {response.json()}")
    except Exception as exc:  # noqa: BLE001 - report any failure the same way
        print(f"\n/healthz check failed at {api_url}: {exc}")
        print("Start the backend first: uv run --project backend python -m uvicorn backend.app:app")
        return 1

    strong, cheap = llm.MODEL_STRONG, llm.MODEL_CHEAP
    table = llm.COST_TABLE
    print("\nCost table (USD per 1M tokens):")
    for label, model in (("strong", strong), ("cheap", cheap)):
        cost = table.get(model)
        if cost is None:
            print(f"  {label:6s} {model}: unpriced (LLM_COST_DEFAULT_IN/_OUT applies)")
        else:
            print(
                f"  {label:6s} {model}: "
                f"in ${cost.usd_per_mtok_in:.2f} / out ${cost.usd_per_mtok_out:.2f}"
            )

    print("\npreflight OK")
    return 0


def cmd_populate_cache(args: argparse.Namespace) -> int:
    from backend.settings import env
    from backend.toolbox.github_tools import (
        component_owners,
        issue_context,
        label_taxonomy,
        similar_issues,
    )

    if not env("GITHUB_TOKEN"):
        raise SystemExit("GITHUB_TOKEN is required to populate the cache")
    os.environ["GITHUB_LIVE"] = "1"

    cases = _load_github_cases()
    print(f"populating cache for {len(cases)} github_triage tasks (GITHUB_LIVE=1) ...")

    label_taxonomy.run({})
    for case in cases:
        case_input = case["input"]
        number = case_input["issue_number"]
        title = case_input.get("title") or ""
        issue_context.run({"issue_number": number, "response_format": "concise"})
        issue_context.run({"issue_number": number, "response_format": "detailed"})
        similar_issues.run({"query": title, "state": "all", "limit": 10})
        keywords = _top_keywords(title)
        if keywords:
            component_owners.run({"paths_or_keywords": keywords})
        print(f"  #{number}: {title[:60]}")

    files = sorted(GITHUB_CACHE_DIR.glob("*.json"))
    total_bytes = sum(f.stat().st_size for f in files)
    print(f"\ncache: {len(files)} files, {total_bytes / 1024:.1f} KiB at {GITHUB_CACHE_DIR}")
    return 0


def _resolve_improve():
    """Lazy import of W6's improver (``ws/w6-improver``, not yet merged to main).

    Kept as an import-time-deferred lookup so this module -- and its
    report-writer tests -- stay usable before that package exists.
    """
    try:
        from backend.improver import improve
    except ImportError as exc:
        raise SystemExit(
            "backend.improver is not available yet (W6 has not merged to main). "
            "Run `domain-a` again once ws/w6-improver lands."
        ) from exc
    return improve


def _resolve_scan_and_record():
    """Lazy import of W8b's persistent playbook scanner.

    W8b lands independently of this branch.  A missing helper must not make
    the Domain A evidence run fail after an otherwise accepted improvement;
    the run can be repeated once W8b is available to backfill the ledger.
    """
    try:
        from backend.playbook import scan_and_record
    except ImportError:
        return None
    return scan_and_record


def _scan_playbook_after_improve(conn: sqlite3.Connection, improve_result: Any) -> list[Any]:
    """Run W8b once for every accepted gate attempt in an improve result.

    W6 currently accepts at most one candidate per ``improve`` call.  Keeping
    this keyed to the individual attempt outcomes makes that condition
    explicit and remains correct if W6 later returns more than one accepted
    attempt.  W8b owns and persists its watermark, so callers intentionally do
    not pass ``since_event_id``.
    """
    accepted_attempts = [
        attempt
        for attempt in getattr(improve_result, "attempts", ())
        if bool(getattr(attempt, "accepted", False))
    ]
    if not accepted_attempts:
        return []

    scan_and_record = _resolve_scan_and_record()
    if scan_and_record is None:
        print(
            "backend.playbook.scan_and_record is not available yet; skipping playbook lesson scan"
        )
        return []

    results = []
    for _attempt in accepted_attempts:
        result = scan_and_record(conn)
        results.append(result)
        print(f"playbook lesson scan: {result}")
    return results


def cmd_domain_a(args: argparse.Namespace) -> int:
    from backend.architect.generate import generate
    from backend.db import init_db
    from backend.runtime.evaluation import run_eval
    from backend.settings import eval_trials
    from backend.toolbox import registry

    conn = init_db()
    try:
        trials = eval_trials()
        if args.agent_id:
            agent_id = args.agent_id
            if agent_row(conn, agent_id) is None:
                raise SystemExit(f"no such agent: {agent_id}")
            print(f"reusing agent {agent_id}")
        else:
            result = generate(
                goal=DOMAIN_A_GOAL,
                domain=DOMAIN_A_DOMAIN,
                tools=list(registry.GITHUB_TOOLS),
                evaluator_id=DOMAIN_A_EVALUATOR,
                use_playbook=False,
                agents_root=AGENTS_DIR,
                evaluators_root=EVALUATORS_DIR,
                conn=conn,
            )
            agent_id = result.agent_id
            print(f"created agent {agent_id} (v{result.version})")

        print(f"running train (trials={trials}) ...")
        run_eval(
            agent_id, split="train", trials=trials,
            agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
        )  # fmt: skip
        print(f"running holdout (trials={trials}) ...")
        run_eval(
            agent_id, split="holdout", trials=trials,
            agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
        )  # fmt: skip

        improve = _resolve_improve()
        print(f"improving (max_attempts={args.max_attempts}) ...")
        improve_result = improve(agent_id, max_attempts=args.max_attempts)
        print(f"improve done: {improve_result}")
        _scan_playbook_after_improve(conn, improve_result)

        report = build_domain_a_report(conn, agent_id, root=REPO_ROOT)
        _write_json(REPORTS_DIR / "domain_a.json", report)
        print(f"wrote {REPORTS_DIR / 'domain_a.json'}")
    finally:
        conn.close()
    return 0


def _playbook_ablation_command(out_path: Path) -> list[str]:
    """Use module execution so the repository root stays on ``sys.path``."""
    return [sys.executable, "-m", "scripts.playbook_ablation", "--out", str(out_path)]


def cmd_domain_b(args: argparse.Namespace) -> int:
    import subprocess

    from backend.db import init_db
    from backend.runtime.evaluation import run_eval
    from backend.settings import eval_trials

    ablation_path = REPORTS_DIR / "ablation.json"
    print("running scripts/playbook_ablation.py (W8) ...")
    subprocess.run(
        _playbook_ablation_command(ablation_path),
        check=True,
        cwd=REPO_ROOT,
    )

    ablation = _load_json(ablation_path)
    if not ablation:
        raise SystemExit(f"{ablation_path} was not written by playbook_ablation.py")
    agent_id = args.agent_id or ablation["agent_ids"]["playbook_on"]

    conn = init_db()
    try:
        trials = eval_trials()
        print(f"running train (trials={trials}) on {agent_id} (playbook on) ...")
        run_eval(
            agent_id, split="train", trials=trials,
            agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
        )  # fmt: skip
        # playbook_ablation.py already ran holdout once while building ablation.json;
        # re-run is unnecessary and would just add a second identical-shape run.

        report = build_domain_b_report(conn, agent_id, root=REPO_ROOT)
        _write_json(REPORTS_DIR / "domain_b.json", report)
        print(f"wrote {REPORTS_DIR / 'domain_b.json'}")
    finally:
        conn.close()
    return 0


def _file_github_issue(note: str, agent_id: str | None) -> None:
    """Open a GitHub issue for a flat/negative number (brief item 5).

    Only called when the caller passed ``--file-issues`` explicitly -- filing
    a public issue is an outward action this script does not take on its own.
    """
    import subprocess

    title = f"[evidence] flat/negative metric: {note[:60]}"
    body = f"Detected while writing reports/summary.md for agent `{agent_id}`:\n\n{note}\n"
    try:
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)
    except Exception as exc:  # noqa: BLE001
        print(f"could not file a GitHub issue automatically ({exc}); title was: {title}")


def cmd_summary(args: argparse.Namespace) -> int:
    domain_a = _load_json(REPORTS_DIR / "domain_a.json")
    if domain_a is None:
        raise SystemExit(f"{REPORTS_DIR / 'domain_a.json'} not found; run `domain-a` first")
    domain_b = _load_json(REPORTS_DIR / "domain_b.json")
    ablation = _load_json(REPORTS_DIR / "ablation.json")
    build_log_text = BUILD_LOG_PATH.read_text(encoding="utf-8") if BUILD_LOG_PATH.is_file() else ""

    markdown = build_summary_markdown(domain_a, domain_b, ablation, build_log_text)
    out_path = REPORTS_DIR / "summary.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"wrote {out_path}")

    flags = flag_regressions(domain_a)
    for flag in flags:
        print(f"FLAGGED: {flag}")
        if getattr(args, "file_issues", False):
            _file_github_issue(flag, domain_a.get("agent_id"))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    for step in (cmd_preflight, cmd_domain_a, cmd_domain_b, cmd_summary):
        rc = step(args)
        if rc != 0:
            return rc
    return 0


# --------------------------------------------------------------------------
# argparse wiring
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="check env vars, /healthz, and print the cost table")
    sub.add_parser(
        "populate-cache", help="record live GitHub responses for every github_triage task"
    )

    domain_a = sub.add_parser(
        "domain-a", help="create/reuse the github_triage agent, run + improve, report"
    )
    domain_a.add_argument(
        "--agent-id", default=None, help="reuse an existing agent instead of creating one"
    )
    domain_a.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)

    domain_b = sub.add_parser(
        "domain-b", help="run the ablation + one train/holdout on the playbook-on agent"
    )
    domain_b.add_argument(
        "--agent-id", default=None, help="use this agent id instead of ablation's playbook_on"
    )

    summary = sub.add_parser(
        "summary", help="write reports/summary.md from the existing reports/*.json"
    )
    summary.add_argument(
        "--file-issues", action="store_true",
        help="open a GitHub issue for each flat/negative number found (default: print only)",
    )  # fmt: skip

    demo = sub.add_parser("demo", help="preflight -> domain-a -> domain-b -> summary")
    demo.add_argument("--agent-id", default=None)
    demo.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    demo.add_argument("--file-issues", action="store_true")

    return parser


COMMANDS = {
    "preflight": cmd_preflight,
    "populate-cache": cmd_populate_cache,
    "domain-a": cmd_domain_a,
    "domain-b": cmd_domain_b,
    "summary": cmd_summary,
    "demo": cmd_demo,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Every default dir above (AGENTS_DIR, run_eval's own relative defaults, and
    # whatever backend.improver defaults to) is only guaranteed correct relative
    # to the repo root -- chdir once here so it does not matter where this was
    # invoked from.
    os.chdir(REPO_ROOT)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
