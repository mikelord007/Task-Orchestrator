"""Export the landing-page fallback from the published evidence reports.

The exporter deliberately does not read the runtime ledger, AO runtime state,
run transcripts, or caches. Missing evidence remains ``null`` in the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"(?:0|[1-9]\d*)(?:\.\d+)?"
MISSING_OR_NUMBER = rf"(?:n/a|{NUMBER})"


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _number(value: str | None) -> float | None:
    if value is None or value == "n/a":
        return None
    return float(value)


def _rate(value: str | None, std: str | None) -> dict[str, float] | None:
    mean_value = _number(value)
    std_value = _number(std)
    if mean_value is None or std_value is None:
        return None
    return {"mean": mean_value, "std": std_value}


def _domain_a_section(summary: str) -> str:
    match = re.search(r"^## Domain A -- .*?(?=^## |\Z)", summary, flags=re.MULTILINE | re.DOTALL)
    return match.group(0) if match else ""


def _parse_summary(summary: str | None) -> dict[str, Any]:
    empty = {
        "domain": None,
        "agent_id": None,
        "baseline_version": None,
        "current_version": None,
        "reported_end_version": None,
        "trials": None,
        "holdout": {
            "pass_at_1": {"before": None, "after": None},
            "pass_pow_k": {"k": None, "before": None, "after": None},
        },
        "fixes": {"accepted": None, "rejected": None},
        "tool_calls_per_task": {
            "split": "train",
            "before": None,
            "after": None,
            "reported_end": None,
        },
    }
    if summary is None:
        return empty

    section = _domain_a_section(summary)
    domain_match = re.search(r"^## Domain A -- ([A-Za-z0-9_-]+)\s*$", section, re.MULTILINE)
    agent_match = re.search(r"^Agent `([^`]+)`, v(\d+) -> v(\d+)\.\s*$", section, re.MULTILINE)
    trials_match = re.search(r"`trials = (\d+)`", summary)
    holdout_match = re.search(
        rf"^- \*\*holdout\*\* pass@1: v\d+ ({MISSING_OR_NUMBER})"
        rf"(?: ± ({MISSING_OR_NUMBER}))? -> v\d+ ({MISSING_OR_NUMBER})"
        rf"(?: ± ({MISSING_OR_NUMBER}))?; pass\^k: v\d+ ({MISSING_OR_NUMBER})"
        rf" -> v\d+ ({MISSING_OR_NUMBER})\s*$",
        section,
        re.MULTILINE,
    )
    fixes_match = re.search(r"^- fix cards: (\d+) accepted, (\d+) rejected;", section, re.MULTILINE)
    tools_match = re.search(
        rf"^- tool calls/errors/tokens per task \(train\): v\d+ calls=({MISSING_OR_NUMBER})"
        rf" .*? -> v\d+ calls=({MISSING_OR_NUMBER}) ",
        section,
        re.MULTILINE,
    )

    baseline_version = int(agent_match.group(2)) if agent_match else None
    reported_end_version = int(agent_match.group(3)) if agent_match else None
    accepted = int(fixes_match.group(1)) if fixes_match else None
    rejected = int(fixes_match.group(2)) if fixes_match else None

    # The summary reports the highest evaluated version, not the accepted
    # current version. Keep current unavailable rather than inferring it from
    # aggregate fix counts.
    current_version = None

    pass_at_1_before = _rate(
        holdout_match.group(1) if holdout_match else None,
        holdout_match.group(2) if holdout_match else None,
    )
    pass_pow_k_before = _number(holdout_match.group(5) if holdout_match else None)
    tool_calls_before = _number(tools_match.group(1) if tools_match else None)
    tool_calls_reported_end = _number(tools_match.group(2) if tools_match else None)

    return {
        "domain": domain_match.group(1) if domain_match else None,
        "agent_id": agent_match.group(1) if agent_match else None,
        "baseline_version": baseline_version,
        "current_version": current_version,
        "reported_end_version": reported_end_version,
        "trials": int(trials_match.group(1)) if trials_match else None,
        "holdout": {
            "pass_at_1": {
                "before": pass_at_1_before,
                "after": None,
            },
            "pass_pow_k": {
                "k": int(trials_match.group(1)) if trials_match else None,
                "before": pass_pow_k_before,
                "after": None,
            },
        },
        "fixes": {"accepted": accepted, "rejected": rejected},
        "tool_calls_per_task": {
            "split": "train",
            "before": tool_calls_before,
            "after": None,
            "reported_end": tool_calls_reported_end,
        },
    }


def _parse_build_log(build_log: str | None) -> dict[str, int | None]:
    if build_log is None:
        return {"sessions": None, "prs": None}
    sessions_section = re.search(
        r"^## Sessions\s*$\n(?P<table>.*?)(?=^## |\Z)",
        build_log,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not sessions_section:
        return {"sessions": None, "prs": None}

    rows = [
        line
        for line in sessions_section.group("table").splitlines()
        if re.match(r"^\| `task-orchestrator-[^`]+` \|", line)
    ]
    session_ids = {match.group(1) for row in rows if (match := re.match(r"^\| `([^`]+)` \|", row))}
    pr_ids: set[int] = set()
    for row in rows:
        columns = row.split("|")
        if len(columns) < 5:
            continue
        pr_column = columns[4]
        match = re.search(r"(?:/pull/|#)(\d+)", pr_column)
        if match:
            pr_ids.add(int(match.group(1)))

    return {
        "sessions": len(session_ids) if session_ids else None,
        "prs": len(pr_ids) if pr_ids else None,
    }


def _parse_ablation(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise ValueError("ablation report must be a JSON object")
    return {
        "domain": report.get("domain"),
        "trials": report.get("trials"),
        "playbook_off": report.get("playbook_off"),
        "playbook_on": report.get("playbook_on"),
        "applied_lesson_ids": report.get("applied_lesson_ids"),
    }


def _corroborating_current_version(raw: str | None) -> int | None:
    if raw is None:
        return None
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise ValueError("Domain A corroboration report must be a JSON object")
    value = report.get("current_version")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _source(path: str, content: str | None) -> dict[str, Any]:
    return {
        "path": path,
        "available": content is not None,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
    }


def export_landing_stats(
    summary: str | None,
    ablation: str | None,
    build_log: str | None,
    domain_a_corroboration: str | None = None,
) -> dict[str, Any]:
    """Return the deterministic, null-safe landing fallback payload."""
    domain_a = _parse_summary(summary)
    ao = _parse_build_log(build_log)
    parsed_ablation = _parse_ablation(ablation)
    corroborating_current = _corroborating_current_version(domain_a_corroboration)
    ablation_result = None
    if parsed_ablation and parsed_ablation["applied_lesson_ids"]:
        playbook_on = parsed_ablation.get("playbook_on") or {}
        playbook_off = parsed_ablation.get("playbook_off") or {}
        with_lessons = playbook_on.get("pass_at_1")
        without_lessons = playbook_off.get("pass_at_1")
        if with_lessons is not None and without_lessons is not None:
            ablation_result = {
                "with_lessons": with_lessons,
                "without_lessons": without_lessons,
            }
    baseline_version = domain_a["baseline_version"]
    tool_calls = domain_a["tool_calls_per_task"]
    return {
        "demo_agent_id": domain_a["agent_id"],
        "domain": domain_a["domain"],
        "current_version": domain_a["current_version"],
        "trials": domain_a["trials"],
        # These arrays intentionally match the existing Insights component's
        # props. The named sources cannot populate the complete RatePoint and
        # Marker shapes without inventing min/max, pass^k spread, or markers.
        "pass_at_1_by_version": [],
        "pass_pow_k_by_version": [],
        "markers": [],
        "chart": None,
        "fixes": domain_a["fixes"],
        "tool_calls_per_task": {
            "split": tool_calls["split"],
            "before": {"version": baseline_version, "value": tool_calls["before"]},
            "after": {"version": None, "value": None},
        },
        "ao_sessions": ao["sessions"],
        "pr_count": ao["prs"],
        "ablation": ablation_result,
        "provenance": {
            "sources": {
                "summary": _source("reports/summary.md", summary),
                "ablation": _source("reports/ablation.json", ablation),
                "build_log": _source("BUILD_LOG.md", build_log),
                "domain_a_corroboration": _source("reports/domain_a.json", domain_a_corroboration),
            },
            "units": {
                "pass_rates": "fraction_0_to_1",
                "tool_calls_per_task": "calls_per_task",
            },
            "semantics": {
                "pass_at_1_std": "std across per-trial task pass rates",
                "pass_pow_k": "fraction of tasks passing all k trials",
                "ao_sessions": "unique worker session ids in BUILD_LOG.md Sessions table",
                "prs": "unique PR ids in BUILD_LOG.md Sessions table",
            },
            "field_sources": {
                "domain_a.agent_and_versions": "reports/summary.md Domain A agent line",
                "domain_a.trials": "reports/summary.md evaluation-method line",
                "domain_a.holdout": "reports/summary.md Domain A holdout line",
                "domain_a.fixes": "reports/summary.md Domain A fix-cards line",
                "domain_a.tool_calls_per_task": "reports/summary.md Domain A train tool-calls line",
                "ao_sessions_and_pr_count": (
                    "BUILD_LOG.md Sessions table; derived from the table, never AO runtime"
                ),
                "ablation": "reports/ablation.json; visible aliases require applied lessons",
                "demo_agent_id": (
                    "reports/summary.md local evidence only; coordination confirms production "
                    "agent list is empty"
                ),
                "provenance.corroborating_current_version": (
                    "reports/domain_a.json current_version; never promoted into visible fallback"
                ),
            },
            "corroborating_current_version": corroborating_current,
            "unavailable_evidence": {
                "baseline_version": baseline_version,
                "reported_end_version": domain_a["reported_end_version"],
                "holdout": domain_a["holdout"],
                "rejected_candidate_tool_calls_per_task": {
                    "split": "train",
                    "version": domain_a["reported_end_version"],
                    "value": tool_calls["reported_end"],
                },
                "ablation": parsed_ablation,
            },
            "limitations": [
                "The summary's highest evaluated version is not necessarily the accepted "
                "current version.",
                "Current-version holdout and tool-call values are unavailable; reported_end "
                "values are rejected-candidate evidence and must not replace them.",
                "Tool-call evidence is train split and must not appear under a holdout caption.",
                "The local Domain A agent id does not establish that the agent exists in "
                "production.",
                "The ablation enabled the playbook but applied_lesson_ids is empty, so it is "
                "not evidence of with-lessons versus without-lessons performance.",
                "BUILD_LOG.md does not establish measured elapsed build duration. PLAN.md "
                "describes a 30-hour hackathon format, not a computed duration.",
            ],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=REPO_ROOT / "reports" / "summary.md")
    parser.add_argument("--ablation", type=Path, default=REPO_ROOT / "reports" / "ablation.json")
    parser.add_argument("--build-log", type=Path, default=REPO_ROOT / "BUILD_LOG.md")
    parser.add_argument(
        "--domain-a-corroboration",
        type=Path,
        default=REPO_ROOT / "reports" / "domain_a.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "frontend" / "lib" / "landing-stats.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = export_landing_stats(
        _read(args.summary),
        _read(args.ablation),
        _read(args.build_log),
        _read(args.domain_a_corroboration),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
