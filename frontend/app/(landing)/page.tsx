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
  trials?: number | null;
  pass_at_1_by_version?: RatePoint[];
  pass_pow_k_by_version?: RatePoint[];
  markers?: Marker[];
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
    const trialCount =
      (liveHasChart && finite(live?.trials) ? live.trials : null) ??
      (finite(fallback.trials) ? fallback.trials : null);
    const liveMarkers = live?.markers ?? [];
    return {
      pass1,
      passK,
      markers: liveHasChart ? liveMarkers : (fallback.markers ?? fallback.chart?.markers ?? []),
      trials: trialCount,
    };
  }, [live]);

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
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 px-6 py-6 sm:px-10 lg:px-16">
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
          <div className="mx-auto max-w-[1440px] px-6 py-20 sm:px-10 sm:py-24 lg:px-16 lg:py-28">
            <p className="eyebrow">Track 1 · Automated Agent Engineering · built with AO</p>
            <h1
              id="hero-title"
              className="display-type mt-10 max-w-[1040px] text-[clamp(1.65rem,6vw,5.5rem)] text-fg"
            >
              <span className="block whitespace-nowrap">Builds the agents</span>
              <span className="block whitespace-nowrap">Improves the agents</span>
              <span className="block whitespace-nowrap">Proves it gets better</span>
            </h1>
            <div className="mt-10 flex flex-wrap items-center gap-7">
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

            {evidence.pass1.length > 0 ? (
              <div className="mt-16">
                {finite(evidence.trials) &&
                evidence.pass1.some((point) => point.split === "holdout") ? (
                  <p className="font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute">
                    Domain A holdout · trials = {evidence.trials} · the improver never sees holdout
                    tasks
                  </p>
                ) : null}
                <div className="mt-4 border border-line-soft bg-ink-700 p-6 sm:p-8">
                  <PassRateChart
                    pass1={evidence.pass1}
                    passK={evidence.passK}
                    markers={evidence.markers}
                  />
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section aria-labelledby="how-title" className="border-b-2 border-line-soft bg-ink-900">
          <div className="mx-auto max-w-[1440px] px-6 py-16 sm:px-10 sm:py-20 lg:px-16 lg:py-24">
            <h2 id="how-title" className="display-type text-4xl text-fg sm:text-5xl">
              How it works
            </h2>
            <div className="mt-12 grid border-x border-t border-line-soft md:grid-cols-2 xl:grid-cols-5">
              {steps.map(([label, copy]) => (
                <article
                  key={label}
                  className="border-b border-line-soft px-6 py-8 md:odd:border-r xl:border-r xl:p-6 xl:last:border-r-0"
                >
                  <p className="text-sm leading-[1.65] text-fg-dim">
                    <strong className="font-sans text-base text-fg">{label}</strong> —{" "}
                    {copy.replace("{k}", finite(evidence.trials) ? String(evidence.trials) : "k")}
                  </p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="different-title" className="border-b-2 border-line-soft">
          <div className="mx-auto max-w-[1440px] px-6 py-16 sm:px-10 sm:py-20 lg:px-16 lg:py-24">
            <h2 id="different-title" className="display-type text-4xl text-fg sm:text-5xl">
              What&apos;s different
            </h2>
            <div className="mt-12 grid gap-6 md:grid-cols-2">
              {differences.map(([title, copy]) => (
                <article key={title} className="border border-line-soft bg-ink-700 p-7 sm:p-8">
                  <h3 className="font-sans text-2xl font-bold text-fg">{title}</h3>
                  <p className="mt-5 max-w-2xl text-sm leading-[1.65] text-fg-dim">{copy}</p>
                </article>
              ))}
            </div>
            <p className="mt-10 max-w-[1100px] text-sm leading-[1.65] text-fg-mute">
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

      <footer className="mx-auto flex max-w-[1440px] flex-col gap-5 px-6 py-10 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute sm:flex-row sm:items-center sm:justify-between sm:px-10 lg:px-16">
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
