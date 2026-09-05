"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { createIssue } from "@/lib/api";
import type { CaseRow, RunSummary, Split } from "@/lib/types";
import { num, pct, shortTs, usd, ms } from "@/lib/format";
import PassStrip from "@/components/PassStrip";
import Stat from "@/components/Stat";
import { DriftBadge, Empty, Pill, Td, Th } from "@/components/ui";

/** Task results for one run, grouped by task, filtered by split and version. */
export default function RunsTab({
  runs,
  agentId,
  ruleText,
}: {
  runs: RunSummary[];
  agentId: string;
  /** rule id -> rule text, so the injected count can name what fired. */
  ruleText: Record<string, string>;
}) {
  const [split, setSplit] = useState<Split | "all">("all");
  const [version, setVersion] = useState<number | "all">("all");

  const versions = useMemo(
    () => Array.from(new Set(runs.map((r) => r.version))).sort((a, b) => b - a),
    [runs],
  );

  const shown = useMemo(
    () =>
      runs
        .filter((r) => (split === "all" ? true : r.split === split))
        .filter((r) => (version === "all" ? true : r.version === version))
        .slice()
        .reverse(),
    [runs, split, version],
  );

  if (runs.length === 0) {
    return (
      <Empty>
        No runs recorded. Press <b className="text-fg">Run train</b> to evaluate this version
        against the train split (the capability suite), or <b className="text-fg">Run holdout</b>{" "}
        for the split the improver never sees.
      </Empty>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-4 border-b border-line pb-2 text-[11px]">
        <Filter
          label="split"
          value={split}
          options={["all", "train", "holdout"]}
          onChange={(v) => setSplit(v as Split | "all")}
        />
        <Filter
          label="version"
          value={String(version)}
          options={["all", ...versions.map((v) => String(v))]}
          format={(v) => (v === "all" ? "all" : `v${v}`)}
          onChange={(v) => setVersion(v === "all" ? "all" : Number(v))}
        />
        <span className="text-fg-mute">
          {shown.length} of {runs.length} runs
        </span>
      </div>

      {shown.length === 0 ? (
        <Empty>No run matches this filter. Widen it, or run that split.</Empty>
      ) : (
        <div className="space-y-8 pt-4">
          {shown.map((run) => (
            <RunBlock key={run.run_id} run={run} agentId={agentId} ruleText={ruleText} />
          ))}
        </div>
      )}
    </div>
  );
}

function RunBlock({
  run,
  agentId,
  ruleText,
}: {
  run: RunSummary;
  agentId: string;
  ruleText: Record<string, string>;
}) {
  const drifted = run.cases.filter((c) => c.drift_kind).length;
  const stable = run.cases.filter((c) => c.passed_by_trial.every(Boolean)).length;

  return (
    <section>
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-2">
        <div className="flex flex-wrap items-baseline gap-3">
          <Pill tone={run.split === "train" ? "train" : "holdout"}>{run.split}</Pill>
          <span className="text-[12px] text-fg">v{run.version}</span>
          <span className="text-[11px] text-fg-mute">{run.run_id}</span>
          <span className="text-[11px] text-fg-mute">
            trials {run.trials} · {run.cases.length} tasks · {shortTs(run.finished_ts)}
          </span>
        </div>
        <div className="flex flex-wrap gap-6">
          <Stat
            label="pass@1"
            rate={run.pass_at_1}
            tone={run.split === "train" ? "train" : "holdout"}
            size="md"
          />
          <Stat
            label="pass^k"
            value={pct(run.pass_pow_k)}
            tone={run.split === "train" ? "train" : "holdout"}
            size="md"
          />
          <Stat label="stable" value={`${stable}/${run.cases.length}`} size="md" />
          <Stat label="cost" value={usd(run.total_cost_usd)} size="md" />
          <Stat label="p50 / p95" value={`${ms(run.p50_latency_ms)} / ${ms(run.p95_latency_ms)}`} size="md" />
          {drifted > 0 ? <Stat label="drifted tasks" value={String(drifted)} tone="drift" size="md" /> : null}
        </div>
      </header>

      <table className="w-full text-[12px]">
        <thead>
          <tr>
            <Th className="w-[13%]">task</Th>
            <Th className="w-[11%]">trials</Th>
            <Th className="w-[7%] text-right">score</Th>
            <Th className="w-[8%] text-right">cost</Th>
            <Th className="w-[8%] text-right">latency</Th>
            <Th className="w-[7%] text-right">tools</Th>
            <Th className="w-[7%] text-right">errors</Th>
            <Th className="w-[11%]">rules</Th>
            <Th className="w-[10%]">drift</Th>
            <Th>links</Th>
          </tr>
        </thead>
        <tbody>
          {run.cases.map((c) => (
            <TaskRow key={c.case_id} run={run} c={c} agentId={agentId} ruleText={ruleText} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TaskRow({
  run,
  c,
  agentId,
  ruleText,
}: {
  run: RunSummary;
  c: CaseRow;
  agentId: string;
  ruleText: Record<string, string>;
}) {
  const failed = c.passed_by_trial.some((p) => !p);

  return (
    <tr>
      <Td>
        <Link
          href={`/agents/${agentId}/compare?case_id=${encodeURIComponent(c.case_id)}`}
          className="text-fg hover:text-train hover:underline"
          title="Compare v0 and the current version on this task"
        >
          {c.case_id}
        </Link>
      </Td>
      <Td>
        <PassStrip passed={c.passed_by_trial} />
        {failed ? <GraderDisagreeButton agentId={agentId} run={run} task={c} /> : null}
      </Td>
      <Td className="text-right tabular-nums text-fg-dim">{num(c.score, 2)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{usd(c.cost_usd)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{ms(c.latency_ms)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{c.tool_calls}</Td>
      <Td className={`text-right tabular-nums ${c.tool_errors > 0 ? "text-fail" : "text-fg-mute"}`}>
        {c.tool_errors}
      </Td>
      <Td>
        {c.rules_injected.length === 0 ? (
          <span className="text-fg-mute">—</span>
        ) : (
          <span
            className="cursor-help text-fg-dim underline decoration-dotted underline-offset-2"
            title={c.rules_injected
              .map((id) => `${id}: ${ruleText[id] ?? "(text not in this version)"}`)
              .join("\n\n")}
          >
            {c.rules_injected.length} injected
          </span>
        )}
      </Td>
      <Td>{c.drift_kind ? <DriftBadge kind={c.drift_kind} /> : null}</Td>
      <Td className="text-[11px]">
        {c.trace_url ? (
          <a href={c.trace_url} target="_blank" rel="noreferrer" className="text-fg-mute hover:text-train">
            trace
          </a>
        ) : null}
        {c.trace_url && c.transcript_path ? <span className="text-fg-mute"> </span> : null}
        {c.transcript_path ? (
          <span className="text-fg-mute" title={c.transcript_path}>
            transcript
          </span>
        ) : null}
      </Td>
    </tr>
  );
}

/**
 * Files a lever=grader issue for review, per addendum J: a grader fix is
 * excluded from the agent's improvement curve. This is a doubt about the
 * verdict, not a claim the agent is right.
 */
function GraderDisagreeButton({
  agentId,
  run,
  task,
}: {
  agentId: string;
  run: RunSummary;
  task: CaseRow;
}) {
  const [state, setState] = useState<"idle" | "busy" | "sent">("idle");

  if (state === "sent") {
    return <span className="ml-2 text-[10px] text-fg-mute">reported</span>;
  }

  return (
    <button
      onClick={async () => {
        setState("busy");
        const failedTrials = task.passed_by_trial.filter((p) => !p).length;
        await createIssue({
          agent_id: agentId,
          title: `Grader disagreed: ${task.case_id}`,
          body: `Filed from the runs table. Task ${task.case_id} at v${run.version} (${run.split}) failed ${failedTrials} of ${run.trials} trials, score ${task.score.toFixed(2)}. Reviewing whether the grader's verdict is correct for this task, not whether the agent is.`,
          tags: ["grader-bug"],
          case_id: task.case_id,
        });
        setState("sent");
      }}
      disabled={state === "busy"}
      title="Open an issue doubting the grader's verdict on this task, not the agent's output"
      className="ml-2 text-[10px] text-fg-mute underline decoration-dotted underline-offset-2 hover:text-drift disabled:opacity-50"
    >
      grader disagreed?
    </button>
  );
}

function Filter({
  label,
  value,
  options,
  onChange,
  format = (v) => v,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  format?: (value: string) => string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-fg-mute">{label}</span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          aria-pressed={value === opt}
          className={`rounded-xs border px-1.5 py-px ${
            value === opt
              ? "border-train/50 text-train"
              : "border-transparent text-fg-mute hover:text-fg-dim"
          }`}
        >
          {format(opt)}
        </button>
      ))}
    </span>
  );
}
