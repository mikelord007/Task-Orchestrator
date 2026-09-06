"""End-to-end demo runner and evidence-report writer (W11 brief, PLAN_ADDENDUM.md).

    uv run --project backend python scripts/demo_run.py preflight
    uv run --project backend python scripts/demo_run.py populate-cache
    uv run --project backend python scripts/demo_run.py domain-a [--agent-id ID]
        [--improve-rounds N] [--attempts-per-round N]
    uv run --project backend python scripts/demo_run.py domain-b [--agent-id ID]
    uv run --project backend python scripts/demo_run.py summary [--no-file-issues]
    uv run --project backend python scripts/demo_run.py demo   # preflight -> domain-a -> domain-b
                                                                 # -> summary

Every number in ``reports/*.json`` and ``reports/summary.md`` is read back from
the ledger (``backend.ledger.metrics``) after a real run -- nothing here is
typed by hand (rule PLAN.md sec 2.8 / brief item "no fabricated numbers").

The improver is imported lazily, and the playbook scanner has an optional
follow-up hook:

* ``backend.improver.improve`` -- imported lazily inside ``cmd_domain_a`` so
  this module and its report-writer tests stay importable without starting it.
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
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.ledger import metrics  # noqa: E402
from backend.ledger.query import agent_row, latest_run  # noqa: E402
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
DEFAULT_IMPROVE_ROUNDS = 4
DEFAULT_ATTEMPTS_PER_ROUND = 3
DOMAIN_B_DOMAIN = "ticket_triage"
DOMAIN_B_EVALUATOR = "ticket_triage"

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
    """Atomically replace a JSON artifact without risking the last checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(data, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_text(path: Path, content: str) -> None:
    """Atomically replace a text artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _fmt(value: float | int | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _money(value: float | int | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"${value:.{digits}f}"


def _known(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _pass_str(mean: float | None, std: float | None) -> str:
    if mean is None:
        return "n/a"
    if std is None:
        return f"{mean:.3f}"
    return f"{mean:.3f} ± {std:.3f}"


def _tool_tokens(row: dict[str, Any] | None) -> str:
    value = _number(row.get("tool_tokens")) if row else None
    if value is None:
        return "n/a"
    qualifier = (
        "estimated"
        if row.get("tool_tokens_estimated") is True
        else "measured"
        if row.get("tool_tokens_estimated") is False
        else "provenance unknown"
    )
    return f"{_fmt(value, 0)} ({qualifier})"


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


def _accepted_version_chain(cards: list[dict[str, Any]], current_version: Any) -> list[int]:
    """Accepted ancestry from v0 to the mutable current-version pointer."""
    if isinstance(current_version, bool) or not isinstance(current_version, int):
        return []
    if current_version == 0:
        return [0]
    accepted = {
        card.get("to_version"): card.get("from_version")
        for card in cards
        if card.get("status") == "accepted"
    }
    chain = [current_version]
    seen = {current_version}
    while chain[-1] != 0:
        parent = accepted.get(chain[-1])
        if isinstance(parent, bool) or not isinstance(parent, int) or parent in seen:
            accepted_versions = sorted(
                version
                for version in accepted
                if isinstance(version, int) and 0 < version <= current_version
            )
            return list(dict.fromkeys([0, *accepted_versions, current_version]))
        chain.append(parent)
        seen.add(parent)
    return list(reversed(chain))


def _accepted_rows(rows: list[dict[str, Any]], versions: list[int]) -> list[dict[str, Any]]:
    accepted = set(versions)
    return [row for row in rows if row.get("version") in accepted]


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
    conn: sqlite3.Connection,
    agent_id: str,
    root: str | Path | None = None,
    *,
    progress: dict[str, Any] | None = None,
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
    current_version = insights.get("current_version")
    accepted_versions = _accepted_version_chain(cards, current_version)
    rejected_versions = sorted(
        {
            card["to_version"]
            for card in cards
            if card.get("status") == "rejected" and isinstance(card.get("to_version"), int)
        }
    )
    progress = dict(progress or {})
    return {
        "agent_id": agent_id,
        "domain": insights.get("domain"),
        "current_version": current_version,
        "accepted_versions": accepted_versions,
        "rejected_candidate_versions": rejected_versions,
        "complete": progress.get("complete"),
        "progress": progress,
        "trials": insights.get("trials"),
        "pass_at_1_by_version": _accepted_rows(insights["pass_at_1_by_version"], accepted_versions),
        "pass_pow_k_by_version": _accepted_rows(
            insights["pass_pow_k_by_version"], accepted_versions
        ),
        "cost_by_version": _accepted_rows(insights["cost_by_version"], accepted_versions),
        "latency_by_version": _accepted_rows(insights["latency_by_version"], accepted_versions),
        "tool_stats_by_version": _accepted_rows(
            insights["tool_stats_by_version"], accepted_versions
        ),
        "memory_by_version": _accepted_rows(insights["memory_by_version"], accepted_versions),
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
    conn: sqlite3.Connection,
    agent_id: str,
    root: str | Path | None = None,
    *,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``reports/domain_b.json``: v0 train + holdout for the playbook-on agent.

    Domain B has no improve iterations (cut per PLAN_ADDENDUM.md sec M --
    ``scripts/playbook_ablation.py`` covers the on/off comparison instead), so
    this is a single version's numbers, not a version-over-version curve.
    """
    row = agent_row(conn, agent_id)
    version = row.get("current_version") if row else None
    metric_version = version if isinstance(version, int) and not isinstance(version, bool) else 0
    report: dict[str, Any] = {
        "agent_id": agent_id,
        "domain": row.get("domain") if row else None,
        "version": version,
        "complete": (progress or {}).get("complete"),
        "progress": dict(progress or {}),
    }
    for split in ("train", "holdout"):
        report[split] = {
            "pass_at_1": metrics.pass_at_1(conn, agent_id, metric_version, split),
            "pass_pow_k": metrics.pass_pow_k(conn, agent_id, metric_version, split),
            "cost_per_run": metrics.cost_per_run(conn, agent_id, metric_version, split),
            "latency": metrics.latency_percentiles(conn, agent_id, metric_version, split),
            "tool_stats": metrics.tool_call_stats(conn, agent_id, metric_version, split, root)[
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flag_regressions(
    domain_a: dict[str, Any],
    domain_b: dict[str, Any] | None = None,
    ablation: dict[str, Any] | None = None,
) -> list[str]:
    """Plain-English notes for every observed flat or negative evidence metric."""
    flags: list[str] = []
    current = domain_a.get("current_version")
    if isinstance(current, int) and not isinstance(current, bool) and current > 0:
        for name, key in (("pass@1", "pass_at_1_by_version"), ("pass^k", "pass_pow_k_by_version")):
            for split in ("train", "holdout"):
                before = _entry_by_version_split(domain_a.get(key, []), 0, split)
                after = _entry_by_version_split(domain_a.get(key, []), current, split)
                before_value = _number(before and before.get("mean"))
                after_value = _number(after and after.get("mean"))
                if (
                    before_value is not None
                    and after_value is not None
                    and after_value <= before_value
                ):
                    flags.append(
                        f"Domain A {split} {name} did not improve v0->v{current}: "
                        f"{before_value:.3f} -> {after_value:.3f}"
                    )

        for split in ("train", "holdout"):
            before = _entry_by_version_split(domain_a.get("cost_by_version", []), 0, split)
            after = _entry_by_version_split(domain_a.get("cost_by_version", []), current, split)
            before_value = _number(before and before.get("cost_per_run"))
            after_value = _number(after and after.get("cost_per_run"))
            if before_value is not None and after_value is not None and after_value >= before_value:
                flags.append(
                    f"Domain A {split} cost per run did not decrease v0->v{current}: "
                    f"${before_value:.4f} -> ${after_value:.4f}"
                )

            latency_before = _entry_by_version_split(
                domain_a.get("latency_by_version", []), 0, split
            )
            latency_after = _entry_by_version_split(
                domain_a.get("latency_by_version", []), current, split
            )
            for field in ("p50_ms", "p95_ms"):
                before_value = _number(latency_before and latency_before.get(field))
                after_value = _number(latency_after and latency_after.get(field))
                if (
                    before_value is not None
                    and after_value is not None
                    and after_value >= before_value
                ):
                    flags.append(
                        f"Domain A {split} latency {field} did not decrease v0->v{current}: "
                        f"{before_value:.0f} -> {after_value:.0f} ms"
                    )

            tool_before = _entry_by_version_split(
                domain_a.get("tool_stats_by_version", []), 0, split
            )
            tool_after = _entry_by_version_split(
                domain_a.get("tool_stats_by_version", []), current, split
            )
            for field in ("calls", "errors", "redundant", "tool_tokens"):
                before_value = _number(tool_before and tool_before.get(field))
                after_value = _number(tool_after and tool_after.get(field))
                if (
                    before_value is not None
                    and after_value is not None
                    and after_value >= before_value
                ):
                    flags.append(
                        f"Domain A {split} tool {field} did not decrease v0->v{current}: "
                        f"{before_value:.3f} -> {after_value:.3f}"
                    )

    if domain_b:
        for split in ("train", "holdout"):
            stats = domain_b.get(split) or {}
            for label, key in (("pass@1", "pass_at_1"), ("pass^k", "pass_pow_k")):
                value = _number((stats.get(key) or {}).get("mean"))
                if value is not None and value <= 0:
                    flags.append(f"Domain B {split} {label} is non-positive: {value:.3f}")

    if ablation:
        off = ablation.get("playbook_off") or {}
        on = ablation.get("playbook_on") or {}
        for label, key in (("pass@1", "pass_at_1"), ("pass^k", "pass_pow_k")):
            off_value = _number(off.get(key))
            on_value = _number(on.get(key))
            if off_value is not None and on_value is not None and on_value <= off_value:
                flags.append(
                    f"Domain B playbook ablation {label} did not improve: "
                    f"off {off_value:.3f} -> on {on_value:.3f}"
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
    lines.append("# Task Orchestrator -- Evidence Summary")
    lines.append("")
    lines.append(f"Generated {generated_at or datetime.now(UTC).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        "Every pass rate below is reported as `pass@1 = mean ± std` and "
        "`pass^k = mean ± std`, with its own observed trial count "
        "(PLAN_ADDENDUM.md sec B/J)."
    )
    lines.append("")

    v0 = 0
    raw_current = domain_a.get("current_version")
    v_n = (
        raw_current if isinstance(raw_current, int) and not isinstance(raw_current, bool) else None
    )
    endpoint = f"v{v_n}" if v_n is not None else "n/a"

    lines.append("## Domain A -- github_triage")
    lines.append("")
    lines.append(f"Agent `{_known(domain_a.get('agent_id'))}`, v{v0} -> {endpoint}.")
    lines.append("")
    for split in ("train", "holdout"):
        p1_before = _entry_by_version_split(domain_a.get("pass_at_1_by_version", []), v0, split)
        p1_after = _entry_by_version_split(domain_a.get("pass_at_1_by_version", []), v_n, split)
        pk_before = _entry_by_version_split(domain_a.get("pass_pow_k_by_version", []), v0, split)
        pk_after = _entry_by_version_split(domain_a.get("pass_pow_k_by_version", []), v_n, split)
        lines.append(
            f"- **{split}** (`trials = {_known((p1_after or p1_before or {}).get('trials'))}`): "
            f"pass@1 = v{v0} "
            f"{_pass_str(p1_before and p1_before.get('mean'), p1_before and p1_before.get('std'))}"
            f" -> {endpoint} "
            f"{_pass_str(p1_after and p1_after.get('mean'), p1_after and p1_after.get('std'))}"
            f"; pass^k = v{v0} "
            f"{_pass_str(pk_before and pk_before.get('mean'), pk_before and pk_before.get('std'))}"
            f" -> {endpoint} "
            f"{_pass_str(pk_after and pk_after.get('mean'), pk_after and pk_after.get('std'))}"
        )
    lines.append("")

    cost_before = _entry_by_version_split(domain_a.get("cost_by_version", []), v0, "train")
    cost_after = _entry_by_version_split(domain_a.get("cost_by_version", []), v_n, "train")
    lat_before = _entry_by_version_split(domain_a.get("latency_by_version", []), v0, "train")
    lat_after = _entry_by_version_split(domain_a.get("latency_by_version", []), v_n, "train")
    lines.append(
        f"- cost per run (train): v{v0} "
        f"{_money(cost_before and cost_before.get('cost_per_run'))}"
        f" -> {endpoint} {_money(cost_after and cost_after.get('cost_per_run'))}"
    )
    lines.append(
        f"- latency p50/p95 (train): v{v0} "
        f"{_fmt(lat_before and lat_before.get('p50_ms'), 0)}/"
        f"{_fmt(lat_before and lat_before.get('p95_ms'), 0)} ms"
        f" -> {endpoint} "
        f"{_fmt(lat_after and lat_after.get('p50_ms'), 0)}/"
        f"{_fmt(lat_after and lat_after.get('p95_ms'), 0)} ms"
    )

    tool_before = _entry_by_version_split(domain_a.get("tool_stats_by_version", []), v0, "train")
    tool_after = _entry_by_version_split(domain_a.get("tool_stats_by_version", []), v_n, "train")
    lines.append(
        "- tool calls/errors/tokens per task (train): "
        f"v{v0} calls={_fmt(tool_before and tool_before.get('calls'), 2)} "
        f"errors={_fmt(tool_before and tool_before.get('errors'), 2)} "
        f"tokens={_tool_tokens(tool_before)}"
        f" -> {endpoint} calls={_fmt(tool_after and tool_after.get('calls'), 2)} "
        f"errors={_fmt(tool_after and tool_after.get('errors'), 2)} "
        f"tokens={_tool_tokens(tool_after)}"
    )
    fixes_by_lever = domain_a.get("fixes_by_lever")
    lines.append(
        f"- fixes by lever: {json.dumps(fixes_by_lever) if fixes_by_lever is not None else 'n/a'}"
    )
    lines.append(
        f"- fix cards: {_known(domain_a.get('fixes_accepted'))} accepted, "
        f"{_known(domain_a.get('fixes_rejected'))} rejected; "
        f"regressions caught: {_known(domain_a.get('regressions_caught'))}"
    )
    drift = domain_a.get("drift") or {}
    drift_by_kind = drift.get("count_by_kind")
    lines.append(
        "- drift by kind: "
        f"{json.dumps(drift_by_kind) if drift_by_kind is not None else 'n/a'}; "
        f"tokens saved: {_known(drift.get('tokens_saved'))}; "
        f"cases recovered by nudge: {_known(drift.get('cases_recovered_by_nudge'))}"
    )
    mem_rows = domain_a.get("memory_by_version", [])
    if mem_rows:
        first = _entry_by_version(mem_rows, v0)
        current = _entry_by_version(mem_rows, v_n)
        if first and current:
            lines.append(
                f"- memory growth: v{v0} rules={_known(first.get('rules'))} "
                f"tool_notes={_known(first.get('tool_notes'))} -> {endpoint} "
                f"rules={_known(current.get('rules'))} "
                f"tool_notes={_known(current.get('tool_notes'))} "
                f"demotions={_known(current.get('demotions'))}"
            )
    rejected_versions = domain_a.get("rejected_candidate_versions")
    if rejected_versions:
        lines.append(f"- rejected candidate versions (not current): {rejected_versions}")
    lines.append(f"- graduated tasks: {_known(domain_a.get('graduated_count'))}")
    lines.append(f"- capability suite saturated: {_known(domain_a.get('saturated'))}")
    lines.append(f"- lessons count (cross-agent playbook): {_known(domain_a.get('lessons_count'))}")
    lines.append("")

    flags = flag_regressions(domain_a, domain_b, ablation)
    if flags:
        lines.append(
            "**Flagged (flat or negative -- reported as-is, not massaged; "
            "the summary command opens a GitHub issue for each unless "
            "`--no-file-issues` is passed):**"
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
            f"Agent `{_known(domain_b.get('agent_id'))}` (playbook on), "
            f"version {_known(domain_b.get('version'))}."
        )
        for split in ("train", "holdout"):
            stat = domain_b.get(split) or {}
            p1 = stat.get("pass_at_1") or {}
            pk = stat.get("pass_pow_k") or {}
            lines.append(
                f"- {split} (`trials = {_known(p1.get('trials') or pk.get('trials'))}`): "
                f"pass@1 = {_pass_str(p1.get('mean'), p1.get('std'))}; "
                f"pass^k = {_pass_str(pk.get('mean'), pk.get('std'))}"
            )
    else:
        lines.append("_not run._")
    lines.append("")

    lines.append("### Playbook ablation (Domain B, playbook on vs off)")
    lines.append("")
    if ablation:
        off, on = ablation.get("playbook_off", {}), ablation.get("playbook_on", {})
        for label, stats in (("off", off), ("on", on)):
            p1_std = stats.get("pass_at_1_std", stats.get("std"))
            pk_std = stats.get("pass_pow_k_std", stats.get("std"))
            lines.append(
                f"- playbook {label} (`trials = {_known(ablation.get('trials'))}`): "
                f"pass@1 = {_pass_str(stats.get('pass_at_1'), p1_std)}, "
                f"pass^k = {_pass_str(stats.get('pass_pow_k'), pk_std)}"
            )
        lesson_ids = ablation.get("applied_lesson_ids")
        lines.append(f"- applied lesson ids: {_known(lesson_ids)}")
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


def _ensure_cache_call(
    github: Any,
    tool_name: str,
    args: dict[str, Any],
    invoke: Any,
    expected: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> Any | None:
    """Populate one primitive cache entry only when it is absent or corrupt."""
    expected.append((tool_name, args))
    cached = github.read_cache(tool_name, args)
    if cached is not None:
        return cached
    result = invoke()
    payload, error = github.decode(result)
    if error is not None:
        call = json.dumps(github.canonical_args(args), sort_keys=True)
        errors.append(f"{tool_name} {call}: {error}")
        return None
    if github.read_cache(tool_name, args) is None:
        errors.append(
            f"{tool_name} {json.dumps(github.canonical_args(args), sort_keys=True)}: "
            "call returned data but no valid cache entry was written"
        )
        return None
    return payload


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
    from backend.toolbox import github
    from backend.toolbox.github_tools import (
        component_owners,
        issue_context,
        label_taxonomy,
        similar_issues,
    )

    if not env("GITHUB_TOKEN"):
        raise SystemExit("GITHUB_TOKEN is required to populate the cache")
    cases = _load_github_cases()
    print(f"populating missing cache entries for {len(cases)} github_triage tasks ...")
    expected: list[tuple[str, dict[str, Any]]] = []
    errors: list[str] = []
    old_live = os.environ.get("GITHUB_LIVE")
    os.environ["GITHUB_LIVE"] = "1"
    try:
        repo = github.repo()
        labels_args = {"repo": repo}
        labels = _ensure_cache_call(
            github,
            "github_list_labels",
            labels_args,
            github.list_labels,
            expected,
            errors,
        )
        for label in (labels or {}).get("labels", []):
            name = label.get("name")
            if not name:
                continue
            query = f'label:"{name}"'
            args_for_label = {
                "repo": repo,
                "q": query,
                "page": 1,
                "per_page": label_taxonomy.EXAMPLE_FETCH,
            }
            _ensure_cache_call(
                github,
                "github_search_issues",
                args_for_label,
                lambda query=query: github.search_issues(
                    query, per_page=label_taxonomy.EXAMPLE_FETCH
                ),
                expected,
                errors,
            )

        for case in cases:
            case_input = case["input"]
            number = int(case_input["issue_number"])
            title = case_input.get("title") or ""
            issue_args = {"repo": repo, "number": number}
            _ensure_cache_call(
                github,
                "github_get_issue",
                issue_args,
                lambda number=number: github.get_issue(number),
                expected,
                errors,
            )
            page_args = {
                "repo": repo,
                "number": number,
                "per_page": github.DEFAULT_PER_PAGE,
            }
            _ensure_cache_call(
                github,
                "github_list_issue_comments",
                page_args,
                lambda number=number: github.list_issue_comments(
                    number, per_page=github.DEFAULT_PER_PAGE
                ),
                expected,
                errors,
            )
            timeline = _ensure_cache_call(
                github,
                "github_get_issue_timeline",
                page_args,
                lambda number=number: github.get_issue_timeline(
                    number, per_page=github.DEFAULT_PER_PAGE
                ),
                expected,
                errors,
            )
            for sha in (timeline or {}).get("commit_shas", [])[: issue_context.MAX_LINKED_ITEMS]:
                commit_args = {"repo": repo, "sha": str(sha)}
                _ensure_cache_call(
                    github,
                    "github_get_commit",
                    commit_args,
                    lambda sha=sha: github.get_commit(str(sha)),
                    expected,
                    errors,
                )

            search_args = {
                "repo": repo,
                "q": title,
                "page": 1,
                "per_page": similar_issues.DEFAULT_LIMIT,
            }
            _ensure_cache_call(
                github,
                "github_search_issues",
                search_args,
                lambda title=title: github.search_issues(
                    title, per_page=similar_issues.DEFAULT_LIMIT
                ),
                expected,
                errors,
            )
            for keyword in _top_keywords(title):
                commit_args = {
                    "repo": repo,
                    "path": keyword,
                    "per_page": component_owners.MAX_COMMITS_PER_TERM,
                }
                _ensure_cache_call(
                    github,
                    "github_list_recent_commits",
                    commit_args,
                    lambda keyword=keyword: github.list_recent_commits(
                        path=keyword, per_page=component_owners.MAX_COMMITS_PER_TERM
                    ),
                    expected,
                    errors,
                )
                owner_search_args = {
                    "repo": repo,
                    "q": keyword,
                    "page": 1,
                    "per_page": component_owners.MAX_ISSUES_PER_TERM,
                }
                _ensure_cache_call(
                    github,
                    "github_search_issues",
                    owner_search_args,
                    lambda keyword=keyword: github.search_issues(
                        keyword, per_page=component_owners.MAX_ISSUES_PER_TERM
                    ),
                    expected,
                    errors,
                )
            print(f"  #{number}: {title[:60]}")
    finally:
        if old_live is None:
            os.environ.pop("GITHUB_LIVE", None)
        else:
            os.environ["GITHUB_LIVE"] = old_live

    missing = [
        f"{tool_name} {json.dumps(github.canonical_args(call_args), sort_keys=True)}"
        for tool_name, call_args in expected
        if github.read_cache(tool_name, call_args) is None
    ]
    if errors or missing:
        details = [
            *(f"ERROR: {item}" for item in errors),
            *(f"MISSING: {item}" for item in missing),
        ]
        raise SystemExit("cache population incomplete:\n" + "\n".join(details))

    files = sorted(github.cache_dir().glob("*.json"))
    total_bytes = sum(f.stat().st_size for f in files)
    print(
        f"\ncache complete: {len(expected)} required calls verified; "
        f"{len(files)} files, {total_bytes / 1024:.1f} KiB at {github.cache_dir()}"
    )
    return 0


def _resolve_improve():
    """Import the improver only when Domain A actually runs."""
    try:
        from backend.improver import improve
    except ImportError as exc:
        raise SystemExit(
            "backend.improver is unavailable; install the backend project before domain-a"
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


def _improve_payload(improve_result: Any) -> dict[str, Any]:
    """Normalize W6's dataclass result and simple test doubles to one mapping."""
    if isinstance(improve_result, dict):
        return improve_result
    payload = getattr(improve_result, "payload", None)
    if callable(payload):
        value = payload()
        if isinstance(value, dict):
            return value
    return {
        "starting_version": getattr(improve_result, "starting_version", None),
        "current_version": getattr(improve_result, "current_version", None),
        "improved": getattr(improve_result, "improved", None),
        "attempts": getattr(improve_result, "attempts", []),
    }


def _round_saturated(improve_result: Any, attempts_per_round: int) -> bool:
    """True when a non-improving round consumed its full diagnosis budget."""
    payload = _improve_payload(improve_result)
    improved = payload.get("improved")
    if improved is None:
        improved = payload.get("current_version") != payload.get("starting_version")
    if improved:
        return False

    attempt_ordinals: list[int] = []
    for index, attempt in enumerate(payload.get("attempts") or [], start=1):
        raw = (
            attempt.get("attempt")
            if isinstance(attempt, dict)
            else getattr(attempt, "attempt", None)
        )
        try:
            attempt_ordinals.append(int(raw if raw is not None else index))
        except (TypeError, ValueError):
            attempt_ordinals.append(index)
    return bool(attempt_ordinals) and max(attempt_ordinals) >= attempts_per_round


def _ledger_progress(conn: sqlite3.Connection, agent_id: str) -> tuple[int, float | None]:
    """Cumulative case executions and observed cost for one agent."""
    case_events = query_events(conn, kind="case_result", agent_id=agent_id)
    costs: list[float] = []
    for event in case_events:
        value = event.get("cost_usd")
        if isinstance(value, bool) or value is None:
            return len(case_events), None
        try:
            costs.append(float(value))
        except (TypeError, ValueError):
            return len(case_events), None
    return len(case_events), sum(costs) if costs else None


def _require_agent(
    conn: sqlite3.Connection, agent_id: str, *, domain: str, evaluator_id: str
) -> dict[str, Any]:
    row = agent_row(conn, agent_id)
    if row is None:
        raise SystemExit(f"no such agent: {agent_id}")
    if row.get("domain") != domain or row.get("evaluator_id") != evaluator_id:
        raise SystemExit(
            f"agent {agent_id} is {row.get('domain')}/{row.get('evaluator_id')}, "
            f"expected {domain}/{evaluator_id}"
        )
    return row


def _run_id(conn: sqlite3.Connection, agent_id: str, version: int, split: str) -> str | None:
    run = latest_run(conn, agent_id, version, split)
    return run.run_id if run is not None else None


def _event_cursor(conn: sqlite3.Connection, agent_id: str) -> int:
    rows = query_events(conn, agent_id=agent_id)
    return rows[-1].id if rows else 0


def _checkpoint_domain_a(
    conn: sqlite3.Connection, agent_id: str, progress: dict[str, Any]
) -> dict[str, Any]:
    report = build_domain_a_report(conn, agent_id, root=REPO_ROOT, progress=progress)
    _write_json(REPORTS_DIR / "domain_a.json", report)
    return report


def _recover_round_cursor(
    conn: sqlite3.Connection,
    agent_id: str,
    progress: dict[str, Any],
    attempts_per_round: int,
) -> tuple[int, bool, bool]:
    """Recover a round completed after its pre-round cursor was checkpointed."""
    completed = int(progress.get("completed_rounds") or 0)
    if progress.get("phase") not in {"improving", "improve_failed"}:
        return completed, bool(progress.get("saturated")), False
    round_number = int(progress.get("round_in_progress") or completed + 1)
    starting_version = progress.get("round_starting_version")
    cursor = int(progress.get("round_event_cursor") or 0)
    row = agent_row(conn, agent_id)
    if row and isinstance(starting_version, int) and row.get("current_version") != starting_version:
        return max(completed, round_number), False, True

    events_since_cursor = query_events(
        conn,
        kind=("fix_proposed", "fix_accepted", "fix_rejected"),
        agent_id=agent_id,
        since=cursor,
    )
    proposed_versions = {
        event.get("to_version")
        for event in events_since_cursor
        if event.kind == "fix_proposed" and event.get("from_version") == starting_version
    }
    outcomes = [
        event
        for event in events_since_cursor
        if event.kind in {"fix_accepted", "fix_rejected"}
        and event.get("to_version") in proposed_versions
    ]
    rejected = [event for event in outcomes if event.kind == "fix_rejected"]
    if len(rejected) >= attempts_per_round:
        return max(completed, round_number), True, False
    if outcomes:
        raise SystemExit(
            "cannot safely resume an interrupted partial improve round: candidate artifacts "
            "exist without a completed acceptance or exhausted rejection budget"
        )
    current_version = row.get("current_version") if row else None
    if isinstance(current_version, int) and (AGENTS_DIR / agent_id).is_dir():
        unfinished_candidates = [
            path.name
            for path in (AGENTS_DIR / agent_id).glob("v*")
            if path.is_dir() and path.name[1:].isdigit() and int(path.name[1:]) > current_version
        ]
        if unfinished_candidates:
            raise SystemExit(
                "cannot safely resume an interrupted improve round: uncommitted candidate "
                f"directories exist ({', '.join(sorted(unfinished_candidates))})"
            )
    return completed, False, False


def _run_improvement_rounds(
    conn: sqlite3.Connection,
    agent_id: str,
    improve: Any,
    *,
    rounds: int,
    attempts_per_round: int,
    started_at: float,
    progress: dict[str, Any] | None = None,
) -> list[Any]:
    """Run independent W6 improve rounds, checkpointing evidence after each one."""
    results: list[Any] = []
    report_path = REPORTS_DIR / "domain_a.json"
    progress = dict(progress or {})
    completed_rounds, recovered_saturation, recovered_acceptance = _recover_round_cursor(
        conn, agent_id, progress, attempts_per_round
    )
    current_row = _require_agent(
        conn, agent_id, domain=DOMAIN_A_DOMAIN, evaluator_id=DOMAIN_A_EVALUATOR
    )
    accepted_rounds = max(
        0,
        len(
            _accepted_version_chain(
                metrics.fix_cards(conn, agent_id), current_row["current_version"]
            )
        )
        - 1,
    )
    completed_rounds = max(completed_rounds, accepted_rounds)
    if recovered_acceptance:
        try:
            scan_and_record = _resolve_scan_and_record()
            if scan_and_record is not None:
                print(f"resuming accepted round's playbook scan: {scan_and_record(conn)}")
        except BaseException as exc:
            progress.update(
                phase="scan_failed",
                complete=False,
                completed_rounds=completed_rounds,
                round_in_progress=None,
                last_error=f"{exc.__class__.__name__}: {exc}",
            )
            _checkpoint_domain_a(conn, agent_id, progress)
            raise
        progress.update(
            phase="round_complete",
            complete=False,
            completed_rounds=completed_rounds,
            round_in_progress=None,
            last_error=None,
        )
        _checkpoint_domain_a(conn, agent_id, progress)
    if recovered_saturation:
        progress.update(
            phase="complete",
            complete=True,
            saturated=True,
            completed_rounds=completed_rounds,
        )
        _checkpoint_domain_a(conn, agent_id, progress)
        return results
    if completed_rounds >= rounds:
        progress.update(
            phase="complete",
            complete=True,
            saturated=bool(progress.get("saturated")),
            requested_rounds=rounds,
            attempts_per_round=attempts_per_round,
            completed_rounds=completed_rounds,
        )
        _checkpoint_domain_a(conn, agent_id, progress)
        return results

    for round_number in range(completed_rounds + 1, rounds + 1):
        print(
            f"improve round {round_number}/{rounds} (attempts_per_round={attempts_per_round}) ..."
        )
        starting_row = _require_agent(
            conn, agent_id, domain=DOMAIN_A_DOMAIN, evaluator_id=DOMAIN_A_EVALUATOR
        )
        progress.update(
            phase="improving",
            complete=False,
            saturated=False,
            requested_rounds=rounds,
            attempts_per_round=attempts_per_round,
            completed_rounds=completed_rounds,
            round_in_progress=round_number,
            round_starting_version=starting_row["current_version"],
            round_event_cursor=_event_cursor(conn, agent_id),
            last_error=None,
        )
        _checkpoint_domain_a(conn, agent_id, progress)

        improve_result: Any | None = None
        saturated = False
        failure_phase: str | None = None
        try:
            improve_result = improve(agent_id, max_attempts=attempts_per_round)
            results.append(improve_result)
            print(f"improve round {round_number} done: {improve_result}")
            saturated = _round_saturated(improve_result, attempts_per_round)
            try:
                _scan_playbook_after_improve(conn, improve_result)
            except BaseException:
                failure_phase = "scan_failed"
                raise
        except BaseException as exc:
            failure_phase = failure_phase or "improve_failed"
            progress["last_error"] = f"{exc.__class__.__name__}: {exc}"
            raise
        finally:
            if improve_result is not None:
                completed_rounds = round_number
            is_complete = saturated or completed_rounds >= rounds
            progress.update(
                phase=failure_phase or ("complete" if is_complete else "round_complete"),
                complete=is_complete and failure_phase is None,
                saturated=saturated,
                completed_rounds=completed_rounds,
                round_in_progress=None,
            )
            _checkpoint_domain_a(conn, agent_id, progress)

            case_count, cost_usd = _ledger_progress(conn, agent_id)
            elapsed_seconds = time.monotonic() - started_at
            print(
                f"checkpointed {report_path} after round {round_number}: "
                f"case_runs={case_count}, elapsed_seconds={elapsed_seconds:.1f}, "
                f"cost_usd={_money(cost_usd, 6)}"
            )

        if saturated:
            print(
                f"capability suite saturated after round {round_number}: "
                f"no improvement in {attempts_per_round} attempts; stopping early"
            )
            break
    return results


def cmd_domain_a(args: argparse.Namespace) -> int:
    from backend.architect.generate import generate
    from backend.db import init_db
    from backend.runtime.evaluation import run_eval
    from backend.settings import eval_trials
    from backend.toolbox import registry

    started_at = time.monotonic()
    conn = init_db()
    try:
        trials = eval_trials()
        existing_report = _load_json(REPORTS_DIR / "domain_a.json")
        progress: dict[str, Any] = {}
        if args.agent_id:
            agent_id = args.agent_id
            _require_agent(conn, agent_id, domain=DOMAIN_A_DOMAIN, evaluator_id=DOMAIN_A_EVALUATOR)
            if isinstance(existing_report, dict) and existing_report.get("agent_id") == agent_id:
                progress = dict(existing_report.get("progress") or {})
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
            progress = {
                "phase": "agent_created",
                "complete": False,
                "saturated": False,
                "requested_rounds": args.improve_rounds,
                "attempts_per_round": args.attempts_per_round,
                "completed_rounds": 0,
                "run_ids": {},
            }
            _checkpoint_domain_a(conn, agent_id, progress)

        resume_phase = progress.get("phase")
        resuming_round = resume_phase in {"improving", "improve_failed", "scan_failed"}
        progress.setdefault("run_ids", {})
        train_run_id = _run_id(conn, agent_id, 0, "train")
        if train_run_id is None:
            print(f"running v0 train (trials={trials}) ...")
            run_eval(
                agent_id, version=0, split="train", trials=trials,
                agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
            )  # fmt: skip
            train_run_id = _run_id(conn, agent_id, 0, "train")
        else:
            print(f"reusing finished v0 train run {train_run_id}")
        progress["run_ids"]["baseline_train"] = train_run_id
        if not resuming_round:
            progress.update(phase="baseline_train_complete", complete=False)
        _checkpoint_domain_a(conn, agent_id, progress)

        holdout_run_id = _run_id(conn, agent_id, 0, "holdout")
        if holdout_run_id is None:
            print(f"running v0 holdout (trials={trials}) ...")
            run_eval(
                agent_id, version=0, split="holdout", trials=trials,
                agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
            )  # fmt: skip
            holdout_run_id = _run_id(conn, agent_id, 0, "holdout")
        else:
            print(f"reusing finished v0 holdout run {holdout_run_id}")
        progress["run_ids"]["baseline_holdout"] = holdout_run_id
        if not resuming_round:
            progress.update(phase="baseline_complete", complete=False)
        _checkpoint_domain_a(conn, agent_id, progress)

        if resume_phase == "scan_failed":
            try:
                scan_and_record = _resolve_scan_and_record()
                if scan_and_record is not None:
                    print(f"resuming failed playbook scan: {scan_and_record(conn)}")
            except BaseException as exc:
                progress.update(
                    phase="scan_failed",
                    complete=False,
                    last_error=f"{exc.__class__.__name__}: {exc}",
                )
                _checkpoint_domain_a(conn, agent_id, progress)
                raise
            progress.update(phase="round_complete", complete=False, last_error=None)
            _checkpoint_domain_a(conn, agent_id, progress)

        improve = _resolve_improve()
        _run_improvement_rounds(
            conn,
            agent_id,
            improve,
            rounds=args.improve_rounds,
            attempts_per_round=args.attempts_per_round,
            started_at=started_at,
            progress=progress,
        )
    finally:
        conn.close()
    return 0


def _playbook_ablation_command(out_path: Path) -> list[str]:
    """Use module execution so the repository root stays on ``sys.path``."""
    return [sys.executable, "-m", "scripts.playbook_ablation", "--out", str(out_path)]


def _validate_ablation(conn: sqlite3.Connection, ablation: Any) -> tuple[str, str] | None:
    if not isinstance(ablation, dict) or ablation.get("domain") != DOMAIN_B_DOMAIN:
        return None
    ids = ablation.get("agent_ids") or {}
    off_id, on_id = ids.get("playbook_off"), ids.get("playbook_on")
    if not isinstance(off_id, str) or not isinstance(on_id, str):
        return None
    for agent_id in (off_id, on_id):
        try:
            row = _require_agent(
                conn, agent_id, domain=DOMAIN_B_DOMAIN, evaluator_id=DOMAIN_B_EVALUATOR
            )
        except SystemExit:
            return None
        if row.get("current_version") != 0 or _run_id(conn, agent_id, 0, "holdout") is None:
            return None
    return off_id, on_id


def cmd_domain_b(args: argparse.Namespace) -> int:
    import subprocess

    from backend.db import init_db
    from backend.runtime.evaluation import run_eval
    from backend.settings import eval_trials

    conn = init_db()
    try:
        ablation_path = REPORTS_DIR / "ablation.json"
        ablation = _load_json(ablation_path)
        validated = _validate_ablation(conn, ablation)
        if args.agent_id:
            _require_agent(
                conn,
                args.agent_id,
                domain=DOMAIN_B_DOMAIN,
                evaluator_id=DOMAIN_B_EVALUATOR,
            )
            if validated is None or validated[1] != args.agent_id:
                raise SystemExit(
                    f"--agent-id {args.agent_id} is not the playbook_on agent in a complete "
                    f"{ablation_path}; refusing to regenerate or mislabel Domain B evidence"
                )
            agent_id = args.agent_id
            print(f"reusing completed ablation for Domain B agent {agent_id}")
        else:
            if validated is None:
                print("running scripts/playbook_ablation.py (W8) ...")
                subprocess.run(
                    _playbook_ablation_command(ablation_path),
                    check=True,
                    cwd=REPO_ROOT,
                )
                ablation = _load_json(ablation_path)
                validated = _validate_ablation(conn, ablation)
                if validated is None:
                    raise SystemExit(
                        f"{ablation_path} is missing or does not describe two valid, "
                        "finished ticket_triage holdout agents"
                    )
            else:
                print(f"reusing completed ablation at {ablation_path}")
            agent_id = validated[1]

        row = _require_agent(
            conn, agent_id, domain=DOMAIN_B_DOMAIN, evaluator_id=DOMAIN_B_EVALUATOR
        )
        if row.get("current_version") != 0:
            raise SystemExit(f"Domain B ablation agent {agent_id} must remain at v0")

        existing = _load_json(REPORTS_DIR / "domain_b.json")
        if (
            isinstance(existing, dict)
            and existing.get("agent_id") == agent_id
            and existing.get("complete") is True
        ):
            print(f"reusing complete {REPORTS_DIR / 'domain_b.json'}")
            return 0

        trials = eval_trials()
        train_run_id = _run_id(conn, agent_id, 0, "train")
        if train_run_id is None:
            print(f"running train (trials={trials}) on {agent_id} (playbook on) ...")
            run_eval(
                agent_id, version=0, split="train", trials=trials,
                agents_dir=AGENTS_DIR, evaluators_dir=EVALUATORS_DIR, runs_dir=RUNS_DIR,
            )  # fmt: skip
            train_run_id = _run_id(conn, agent_id, 0, "train")
        else:
            print(f"reusing finished Domain B train run {train_run_id}")

        holdout_run_id = _run_id(conn, agent_id, 0, "holdout")
        if holdout_run_id is None:
            raise SystemExit(f"ablation agent {agent_id} has no finished holdout run")
        progress = {
            "phase": "complete",
            "complete": True,
            "run_ids": {"train": train_run_id, "holdout": holdout_run_id},
            "ablation_path": str(ablation_path.relative_to(REPO_ROOT)),
        }
        report = build_domain_b_report(conn, agent_id, root=REPO_ROOT, progress=progress)
        _write_json(REPORTS_DIR / "domain_b.json", report)
        print(f"wrote {REPORTS_DIR / 'domain_b.json'}")
    finally:
        conn.close()
    return 0


def _file_github_issue(note: str, agent_id: str | None) -> None:
    """Open one deduplicated GitHub issue for a flat/negative number."""
    import subprocess

    title = f"[evidence] flat/negative metric: {note[:60]}"
    body = f"Detected while writing reports/summary.md for agent `{agent_id}`:\n\n{note}\n"
    listed = subprocess.run(
        ["gh", "issue", "list", "--state", "all", "--limit", "100", "--json", "title"],
        check=True,
        capture_output=True,
        text=True,
    )
    existing_titles = {row.get("title") for row in json.loads(listed.stdout or "[]")}
    if title in existing_titles:
        print(f"issue already exists: {title}")
        return
    subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)


def cmd_summary(args: argparse.Namespace) -> int:
    domain_a = _load_json(REPORTS_DIR / "domain_a.json")
    if domain_a is None:
        raise SystemExit(f"{REPORTS_DIR / 'domain_a.json'} not found; run `domain-a` first")
    domain_b = _load_json(REPORTS_DIR / "domain_b.json")
    ablation = _load_json(REPORTS_DIR / "ablation.json")
    if domain_a.get("complete") is not True:
        progress = domain_a.get("progress") or {}
        raise SystemExit(
            "reports/domain_a.json is a partial checkpoint "
            f"(phase={progress.get('phase')!r}, "
            f"completed_rounds={progress.get('completed_rounds')!r}); resume domain-a first"
        )
    if isinstance(domain_b, dict) and domain_b.get("complete") is not True:
        raise SystemExit("reports/domain_b.json is a partial checkpoint; resume domain-b first")
    build_log_text = BUILD_LOG_PATH.read_text(encoding="utf-8") if BUILD_LOG_PATH.is_file() else ""

    markdown = build_summary_markdown(domain_a, domain_b, ablation, build_log_text)
    out_path = REPORTS_DIR / "summary.md"
    _write_text(out_path, markdown)
    print(f"wrote {out_path}")

    flags = flag_regressions(domain_a, domain_b, ablation)
    for flag in flags:
        print(f"FLAGGED: {flag}")
        if getattr(args, "file_issues", False):
            _file_github_issue(flag, domain_a.get("agent_id"))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    domain_a_args = argparse.Namespace(**vars(args), agent_id=args.domain_a_agent_id)
    domain_b_args = argparse.Namespace(**vars(args), agent_id=args.domain_b_agent_id)
    for step, step_args in (
        (cmd_preflight, args),
        (cmd_domain_a, domain_a_args),
        (cmd_domain_b, domain_b_args),
        (cmd_summary, args),
    ):
        rc = step(step_args)
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
    domain_a.add_argument(
        "--improve-rounds",
        type=_positive_int,
        default=DEFAULT_IMPROVE_ROUNDS,
        help="number of independent improve() calls (default: 4)",
    )
    domain_a.add_argument(
        "--attempts-per-round",
        type=_positive_int,
        default=DEFAULT_ATTEMPTS_PER_ROUND,
        help="maximum diagnosis attempts within each improve() call (default: 3)",
    )

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
        "--no-file-issues",
        action="store_false",
        dest="file_issues",
        default=True,
        help="print flat/negative findings without opening the required GitHub issues",
    )

    demo = sub.add_parser("demo", help="preflight -> domain-a -> domain-b -> summary")
    demo.add_argument("--domain-a-agent-id", default=None)
    demo.add_argument("--domain-b-agent-id", default=None)
    demo.add_argument("--improve-rounds", type=_positive_int, default=DEFAULT_IMPROVE_ROUNDS)
    demo.add_argument(
        "--attempts-per-round", type=_positive_int, default=DEFAULT_ATTEMPTS_PER_ROUND
    )
    demo.add_argument("--no-file-issues", action="store_false", dest="file_issues", default=True)

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
