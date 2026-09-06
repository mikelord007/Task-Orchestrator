"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Brand from "@/components/Brand";
import PassRateChart from "@/components/insights/PassRateChart";
import { getInsights } from "@/lib/api";
import type { Insights, Marker, RatePoint } from "@/lib/types";
import landingStatsJson from "@/lib/landing-stats.json";

const SOURCE_URL = "https://github.com/mikelord007/Task-Orchestrator";
const DEMO_AGENT_ID = process.env.NEXT_PUBLIC_DEMO_AGENT_ID;

const steps = [
  ["Generate", "A goal, tools, and a grader become a versioned agent package."],
  ["Run", "Every task, {k} trials. Uncertainty stays attached to every rate."],
  ["Reflect", "The agent reads its recorded transcript and the grade. It is never asked how it did."],
  ["Improve", "One lever per change: memory, tools, prompt, or orchestration."],
  ["Gate", "The full suite runs on the candidate. If a stable task breaks, the change is rejected and kept on record."],
] as const;

const differences = [
  [
    "Error bars, not accuracy.",
    "Reports pass@1 and pass^k over repeated trials, on a holdout the improver never sees. Domain A uses real GitHub issues with a temporal split: train on the oldest, test on the newest.",
  ],
  [
    "The gate says no.",
    "Every candidate runs the whole suite. Regressions are rejected, and rejected fixes stay visible as evidence.",
  ],
  [
    "Memory that corrects itself.",
    "Rules and tool notes carry their evidence and hit/miss counts. A rule that misses more than it hits is demoted automatically.",
  ],
  [
    "Every fix has a card.",
    "Failing group → hypothesis → lever → the actual diff → before and after.",
  ],
] as const;

interface LandingStats {
  current_version?: number | null;
  trials?: number | null;
  pass_at_1_by_version?: RatePoint[];
  pass_pow_k_by_version?: RatePoint[];
  markers?: Marker[];
  fixes?: { accepted?: number | null; rejected?: number | null } | null;
  tool_calls_per_task?: {
    split?: string | null;
    before?: { version?: number | null; value?: number | null } | null;
    after?: { version?: number | null; value?: number | null } | null;
  } | null;
  ao_sessions?: number | null;
  pr_count?: number | null;
  ablation?: {
    playbook_off?: { pass_at_1?: number | null } | null;
    playbook_on?: { pass_at_1?: number | null } | null;
    applied_lesson_ids?: string[] | null;
  } | null;
  chart?: {
    pass_at_1_by_version?: RatePoint[];
    pass_pow_k_by_version?: RatePoint[];
    markers?: Marker[];
  } | null;
}

const fallback = landingStatsJson as LandingStats;

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function decimal(value: number): string {
  return value.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
}

function currentVersion(points: RatePoint[], preferred?: number | null): number | null {
  if (finite(preferred)) return preferred;
  if (points.length === 0) return null;
  return Math.max(...points.map((point) => point.version));
}

function transition(
  points: RatePoint[],
  version: number | null,
  split: "train" | "holdout",
): { before: RatePoint; after: RatePoint } | null {
  if (version === null || version === 0) return null;
  const before = points.find((point) => point.version === 0 && point.split === split);
  const after = points.find((point) => point.version === version && point.split === split);
  return before && after ? { before, after } : null;
}

function liveToolCalls(
  insights: Insights,
): LandingStats["tool_calls_per_task"] {
  const holdout = insights.tool_stats_by_version
    .filter((point) => point.split === "holdout" && finite(point.calls))
    .sort((a, b) => a.version - b.version);
  if (holdout.length < 2) return null;
  return {
    split: "holdout",
    before: { version: holdout[0].version, value: holdout[0].calls },
    after: {
      version: holdout[holdout.length - 1].version,
      value: holdout[holdout.length - 1].calls,
    },
  };
}

function statCell(label: string, value: string) {
  return { label, value };
}

export default function LandingPage() {
  const [live, setLive] = useState<Insights | null>(null);

  useEffect(() => {
    if (!DEMO_AGENT_ID) return;
    let cancelled = false;
    getInsights(DEMO_AGENT_ID)
      .then((value) => {
        if (!cancelled) setLive(value);
      })
      .catch(() => {
        // The checked-in evidence remains visible when the live demo agent is unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const evidence = useMemo(() => {
    const liveHasChart =
      (live?.pass_at_1_by_version.length ?? 0) > 0 &&
      (live?.pass_pow_k_by_version.length ?? 0) > 0;
    const pass1 = liveHasChart
      ? live!.pass_at_1_by_version
      : (fallback.pass_at_1_by_version ?? fallback.chart?.pass_at_1_by_version ?? []);
    const passK = liveHasChart
      ? live!.pass_pow_k_by_version
      : (fallback.pass_pow_k_by_version ?? fallback.chart?.pass_pow_k_by_version ?? []);
    const version = currentVersion(
      pass1,
      liveHasChart ? live?.current_version : fallback.current_version,
    );
    const trialCount =
      (liveHasChart && finite(live?.trials) ? live.trials : null) ??
      (finite(fallback.trials) ? fallback.trials : null);
    const liveMarkers = live?.markers ?? [];
    const liveFixes = liveHasChart && live
      ? {
          accepted: liveMarkers.filter((marker) => marker.kind === "fix_accepted").length,
          rejected: liveMarkers.filter((marker) => marker.kind === "fix_rejected").length,
        }
      : null;
    return {
      pass1,
      passK,
      markers: liveHasChart ? liveMarkers : (fallback.markers ?? fallback.chart?.markers ?? []),
      version,
      trials: trialCount,
      fixes: liveFixes ?? fallback.fixes ?? null,
      toolCalls:
        (liveHasChart && live ? liveToolCalls(live) : null) ??
        fallback.tool_calls_per_task ??
        null,
    };
  }, [live]);

  const stats = useMemo(() => {
    const cells: { label: string; value: string }[] = [];
    const liveHoldoutPass1 = transition(evidence.pass1, evidence.version, "holdout");
    const liveHoldoutPassK = transition(evidence.passK, evidence.version, "holdout");
    const pass1Before = liveHoldoutPass1?.before;
    const pass1After = liveHoldoutPass1?.after;
    if (
      finite(pass1Before?.mean) &&
      finite(pass1Before.std) &&
      finite(pass1After?.mean) &&
      finite(pass1After.std)
    ) {
      cells.push(
        statCell(
          "Holdout pass@1 · GitHub triage",
          `${percent(pass1Before.mean)} ± ${percent(pass1Before.std)} → ${percent(pass1After.mean)} ± ${percent(pass1After.std)}`,
        ),
      );
    }
    const passKBefore = liveHoldoutPassK?.before.mean;
    const passKAfter = liveHoldoutPassK?.after.mean;
    const passKTrials = (liveHoldoutPassK && evidence.trials) ?? evidence.trials;
    if (finite(passKBefore) && finite(passKAfter) && finite(passKTrials)) {
      cells.push(
        statCell(
          `Holdout pass^${passKTrials}`,
          `${percent(passKBefore)} → ${percent(passKAfter)}`,
        ),
      );
    }
    if (finite(evidence.fixes?.accepted) && finite(evidence.fixes?.rejected)) {
      cells.push(
        statCell(
          "Fixes accepted / rejected",
          `${evidence.fixes.accepted} / ${evidence.fixes.rejected}`,
        ),
      );
    }
    const toolBefore = evidence.toolCalls?.before?.value;
    const toolAfter = evidence.toolCalls?.after?.value;
    if (
      evidence.toolCalls?.split === "holdout" &&
      finite(toolBefore) &&
      finite(toolAfter)
    ) {
      cells.push(statCell("Tool calls per task", `${decimal(toolBefore)} → ${decimal(toolAfter)}`));
    }
    if (finite(fallback.ao_sessions)) {
      cells.push(statCell("AO sessions", String(fallback.ao_sessions)));
    }
    return cells;
  }, [evidence]);

  const ablation = fallback.ablation;
  const hasAblation =
    (ablation?.applied_lesson_ids?.length ?? 0) > 0 &&
    finite(ablation?.playbook_on?.pass_at_1) &&
    finite(ablation?.playbook_off?.pass_at_1);

  return (
    <div className="min-h-screen overflow-x-clip bg-ink-800">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-fg focus:p-3 focus:text-ink-900"
      >
        Skip to content
      </a>
      <header className="border-b-2 border-line-soft bg-ink-900">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 px-5 py-5 sm:px-8 lg:px-12">
          <Brand />
          <nav
            aria-label="Landing navigation"
            className="flex items-center gap-5 font-mono text-[10px] font-bold uppercase tracking-[0.08em]"
          >
            <Link href="/agents" className="text-fg-dim hover:text-[#ff9783]">
              Dashboard →
            </Link>
            <a href={SOURCE_URL} className="text-fg-dim hover:text-[#ff9783]">
              Source
            </a>
          </nav>
        </div>
      </header>

      <main id="main">
        <section aria-labelledby="hero-title" className="border-b-2 border-line-soft">
          <div className="mx-auto max-w-[1440px] px-5 py-14 sm:px-8 lg:px-12 lg:py-20">
            <p className="eyebrow">Track 1 · Automated Agent Engineering · built with AO</p>
            <h1
              id="hero-title"
              className="display-type mt-7 max-w-[1180px] text-[clamp(2.75rem,6.5vw,6.8rem)] text-fg"
            >
              Give it a goal, tools, and a grader. It builds the agent and proves each improvement.
            </h1>
            <p className="mt-7 max-w-[900px] text-base leading-[1.55] text-fg-body sm:text-lg">
              Task Orchestrator generates an agent, runs it against a task suite with repeated trials,
              reflects on its recorded failures, changes one lever at a time, and rejects any change
              that regresses. Every number on this page is derived from its append-only ledger.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-5">
              <Link
                href="/agents"
                className="inline-flex border border-fg bg-fg px-4 py-3 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-ink-900 hover:border-[#ff9783] hover:bg-[#ff9783]"
              >
                Open dashboard →
              </Link>
              <a
                href={SOURCE_URL}
                className="font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-fg-dim underline decoration-line underline-offset-4 hover:text-[#ff9783]"
              >
                View source
              </a>
            </div>

            {stats.length > 0 ? (
              <dl className="mt-12 grid border-x border-t border-line-soft sm:grid-cols-2 xl:grid-cols-5">
                {stats.map((stat) => (
                  <div
                    key={stat.label}
                    className="min-w-0 border-b border-line-soft p-5 sm:p-6 sm:odd:border-r xl:border-r xl:last:border-r-0"
                  >
                    <dt className="small-label text-fg-mute">{stat.label}</dt>
                    <dd className="mt-4 break-words font-mono text-xl font-bold tabular-nums text-fg sm:text-2xl">
                      {stat.value}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {finite(evidence.trials) &&
            evidence.pass1.some((point) => point.split === "holdout") ? (
              <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute">
                Domain A holdout · trials = {evidence.trials} · the improver never sees holdout tasks
              </p>
            ) : null}

            {evidence.pass1.length > 0 ? (
              <div className="mt-10 border border-line-soft bg-ink-700 p-5 sm:p-6">
                <PassRateChart
                  pass1={evidence.pass1}
                  passK={evidence.passK}
                  markers={evidence.markers}
                />
              </div>
            ) : null}
          </div>
        </section>

        <section aria-labelledby="how-title" className="border-b-2 border-line-soft bg-ink-900">
          <div className="mx-auto max-w-[1440px] px-5 py-14 sm:px-8 lg:px-12 lg:py-18">
            <h2 id="how-title" className="display-type text-4xl text-fg sm:text-5xl">
              How it works
            </h2>
            <div className="mt-9 grid border-x border-t border-line-soft md:grid-cols-2 xl:grid-cols-5">
              {steps.map(([label, copy]) => (
                <article
                  key={label}
                  className="border-b border-line-soft p-5 md:odd:border-r xl:border-r xl:last:border-r-0"
                >
                  <p className="text-sm leading-[1.5] text-fg-dim">
                    <strong className="font-sans text-base text-fg">{label}</strong> —{" "}
                    {copy.replace("{k}", finite(evidence.trials) ? String(evidence.trials) : "k")}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="different-title" className="border-b-2 border-line-soft">
          <div className="mx-auto max-w-[1440px] px-5 py-14 sm:px-8 lg:px-12 lg:py-18">
            <h2 id="different-title" className="display-type text-4xl text-fg sm:text-5xl">
              What&apos;s different
            </h2>
            <div className="mt-9 grid gap-4 md:grid-cols-2">
              {differences.map(([title, copy]) => (
                <article key={title} className="border border-line-soft bg-ink-700 p-6 sm:p-7">
                  <h3 className="font-sans text-2xl font-bold text-fg">{title}</h3>
                  <p className="mt-4 max-w-2xl text-sm leading-[1.55] text-fg-dim">{copy}</p>
                </article>
              ))}
            </div>
            <p className="mt-7 max-w-[1100px] text-sm leading-[1.55] text-fg-mute">
              Two domains: GitHub issue triage (real API, four consolidated tools, cached for
              deterministic evals) and support ticket triage, where the playbook transfers lessons
              from the first domain.
              {hasAblation
                ? ` — ${percent(ablation!.playbook_on!.pass_at_1!)} with lessons vs ${percent(ablation!.playbook_off!.pass_at_1!)} without.`
                : null}
            </p>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-[1440px] flex-col gap-5 px-5 py-7 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-12">
        {finite(fallback.ao_sessions) && finite(fallback.pr_count) ? (
          <span>
            Built in 30 hours with AO · {fallback.ao_sessions} worker sessions · {fallback.pr_count} PRs
          </span>
        ) : null}
        <span className="flex items-center gap-5">
          <Link href="/agents" className="hover:text-[#ff9783]">
            Dashboard
          </Link>
          <span aria-hidden="true">·</span>
          <a href={SOURCE_URL} className="hover:text-[#ff9783]">
            Source
          </a>
        </span>
      </footer>
    </div>
  );
}
