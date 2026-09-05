"use client";

import { useState } from "react";
import type { FixCard as FixCardData } from "@/lib/types";
import { DASH, delta, num, pct, shortTs, usd } from "@/lib/format";
import DiffView from "./DiffView";
import MemoryEntries from "./MemoryEntries";
import { LeverChip, Pill } from "./ui";

const REJECT_REASON = {
  regression: "a task that had been passing every trial (pass^k) started failing",
  no_gain: "the candidate did not beat the current version's pass@1",
  error: "the candidate could not be evaluated",
} as const;

/**
 * One improvement attempt, accepted or rejected. Shared by the agent Fixes tab,
 * the issue timeline and the insights page, so it takes its agent id explicitly
 * rather than reading a route param.
 */
export default function FixCard({
  card,
  agentId,
  defaultExpanded = false,
}: {
  card: FixCardData;
  agentId: string;
  defaultExpanded?: boolean;
}) {
  const [showDetail, setShowDetail] = useState(defaultExpanded);
  const accepted = card.status === "accepted";
  const isMemory = card.lever === "memory" && (card.memory_entries?.length ?? 0) > 0;

  return (
    <article className="border-t border-line py-4">
      <header className="flex flex-wrap items-center gap-2">
        <Pill tone={accepted ? "pass" : "fail"}>{card.status}</Pill>
        <LeverChip lever={card.lever} />
        <span className="text-[12px] text-fg">
          v{card.from_version} → v{card.to_version}
        </span>
        <span className="text-[11px] text-fg-mute">{shortTs(card.ts)}</span>
      </header>

      <FailingGroup card={card} />

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <Labelled term="Hypothesis">{card.hypothesis}</Labelled>
          <Labelled term="Diagnosis">{card.diagnosis}</Labelled>
          {card.metric_signal ? (
            <Labelled term="Metric signal">{card.metric_signal}</Labelled>
          ) : null}

          {!accepted ? (
            <div className="mt-2 border-l-2 border-fail/50 pl-3">
              <p className="text-[12px] text-fail">
                Gate rejected: {card.reason ? REJECT_REASON[card.reason] : "regression"}.
              </p>
              {card.regressed_case_ids?.length ? (
                <p className="mt-0.5 text-[11px] text-fg-dim">
                  Regressed: {card.regressed_case_ids.join(", ")}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <BeforeAfter card={card} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={() => setShowDetail((v) => !v)}
          className="rounded-xs border border-line px-2 py-0.5 text-[11px] text-fg-dim hover:border-fg-mute hover:text-fg"
        >
          {showDetail ? "hide" : isMemory ? "show memory entries" : "show diff"}
        </button>
        <span className="text-[11px] text-fg-mute">{card.diff_summary}</span>
        {card.files_touched.length ? (
          <span className="text-[11px] text-fg-mute">{card.files_touched.join("  ")}</span>
        ) : null}
      </div>

      {showDetail ? (
        isMemory ? (
          <MemoryEntries entries={card.memory_entries!} />
        ) : (
          <DiffView agentId={agentId} toVersion={card.to_version} />
        )
      ) : null}
    </article>
  );
}

function Labelled({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="mt-2 first:mt-0">
      <span className="text-[11px] text-fg-mute">{term}</span>
      <p className="prose-h mt-0.5 text-fg">{children}</p>
    </div>
  );
}

function FailingGroup({ card }: { card: FixCardData }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 text-[12px]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-left text-fg-dim hover:text-fg"
        title="Show the task ids in this failure group"
      >
        <span className="text-fg-mute">group</span> {card.failing_group.tag}{" "}
        <span className="text-fg-mute">×{card.failing_group.count}</span>{" "}
        <span className="text-fg-mute">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <div className="mt-1 border-l-2 border-ink-600 pl-3 text-[11px] text-fg-dim">
          <div className="text-fg-mute">{card.failing_group.signature}</div>
          <div>{card.failing_group.case_ids.join(", ")}</div>
        </div>
      ) : null}
    </div>
  );
}

function BeforeAfter({ card }: { card: FixCardData }) {
  const rows: {
    label: string;
    before: string;
    after: string;
    change: string;
    tone?: "train" | "holdout";
  }[] = [
    {
      label: "pass@1",
      before: withSpread(card.before.pass_at_1, card.before.pass_at_1_std),
      after: withSpread(card.after.pass_at_1, card.after.pass_at_1_std),
      change: delta(card.before.pass_at_1, card.after.pass_at_1),
      tone: "train",
    },
    {
      label: "pass^k",
      before: pct(card.before.pass_pow_k),
      after: pct(card.after.pass_pow_k),
      change: delta(card.before.pass_pow_k, card.after.pass_pow_k),
      tone: "train",
    },
    {
      label: "group pass",
      before: pct(card.before.group_pass),
      after: pct(card.after.group_pass),
      change: delta(card.before.group_pass, card.after.group_pass),
    },
    {
      label: "holdout pass@1",
      before: DASH,
      after: withSpread(card.after.holdout_pass_at_1, card.after.holdout_pass_at_1_std),
      change: DASH,
      tone: "holdout",
    },
    {
      label: "holdout pass^k",
      before: DASH,
      after: pct(card.after.holdout_pass_pow_k),
      change: DASH,
      tone: "holdout",
    },
    {
      label: "cost per run",
      before: usd(card.before.cost_per_run),
      after: usd(card.after.cost_per_run),
      change: delta(card.before.cost_per_run, card.after.cost_per_run, 1000, 1),
    },
    {
      label: "tool calls/task",
      before: num(card.before.tool_calls_per_task, 1),
      after: num(card.after.tool_calls_per_task, 1),
      change: delta(card.before.tool_calls_per_task, card.after.tool_calls_per_task, 1, 1),
    },
  ];

  return (
    <table className="h-fit w-full text-[11px]">
      <thead>
        <tr className="text-fg-mute">
          <th className="border-b border-line py-1 text-left font-normal">before → after</th>
          <th className="border-b border-line py-1 text-right font-normal">before</th>
          <th className="border-b border-line py-1 text-right font-normal">after</th>
          <th className="border-b border-line py-1 text-right font-normal">Δ</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="border-b border-line-soft py-1 text-fg-mute">{r.label}</td>
            <td className="border-b border-line-soft py-1 text-right tabular-nums text-fg-dim">
              {r.before}
            </td>
            <td
              className={`border-b border-line-soft py-1 text-right tabular-nums ${
                r.tone === "holdout" ? "text-holdout" : r.tone === "train" ? "text-train" : "text-fg"
              }`}
            >
              {r.after}
            </td>
            <td className="border-b border-line-soft py-1 text-right tabular-nums text-fg-mute">
              {r.change}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function withSpread(mean: number | null | undefined, std: number | null | undefined): string {
  if (mean === null || mean === undefined) return DASH;
  if (std === null || std === undefined) return pct(mean);
  return `${pct(mean)} ± ${num(std * 100, 1)}`;
}
