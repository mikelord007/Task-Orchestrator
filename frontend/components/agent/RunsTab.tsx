"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getJob } from "@/lib/api";
import type { Job, RunSummary, Split, TaskResult } from "@/lib/types";
import { num, pct, shortTs, usd, ms } from "@/lib/format";
import PassStrip from "@/components/PassStrip";
import Stat from "@/components/Stat";
import { Button, DriftBadge, Empty, Pill, Td, Th } from "@/components/ui";

const PAGE_SIZE = 10;
const MAX_STATUS_LOOKUPS = 20;
const ACTIVE_POLL_MS = 2_000;

type RunJob = Pick<Job, "status" | "error">;
type RunJobs = Record<string, RunJob | null | undefined>;

/** Task results for one run, grouped by task, filtered by split and version. */
export default function RunsTab({
  runs,
  agentId,
  ruleText,
  onTerminal,
}: {
  runs: RunSummary[];
  agentId: string;
  /** rule id -> rule text, so the injected count can name what fired. */
  ruleText: Record<string, string>;
  /** Refresh final report fields when a run observed here reaches a terminal state. */
  onTerminal: () => void;
}) {
  const [split, setSplit] = useState<Split | "all">("all");
  const [version, setVersion] = useState<number | "all">("all");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const jobs = useUnfinishedRunJobs(runs, onTerminal);

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
        .sort((a, b) => runTime(b) - runTime(a)),
    [runs, split, version],
  );

  useEffect(() => setVisible(PAGE_SIZE), [split, version]);

  if (runs.length === 0) {
    return (
      <Empty>
        No run history yet. Press <b className="text-fg">Run train</b> to evaluate this version
        against the train split (the capability suite), or <b className="text-fg">Run holdout</b>{" "}
        for the split the improver never sees.
      </Empty>
    );
  }

  return (
    <div>
      <div className="border-b border-line pb-3">
        <p className="mb-3 max-w-[82ch] text-[11px] leading-5 text-fg-mute">
          Persisted evaluation history, newest first. Completed runs include their recorded report
          and task results; a dash means the backend did not record that value.
        </p>
        <div className="flex flex-wrap items-center gap-4 text-[11px]">
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
      </div>

      {shown.length === 0 ? (
        <Empty>No run matches this filter. Widen it, or run that split.</Empty>
      ) : (
        <div className="space-y-8 pt-4">
          {shown.slice(0, visible).map((run, index) => (
            <RunBlock
              key={run.run_id}
              run={run}
              job={jobs[run.run_id]}
              agentId={agentId}
              ruleText={ruleText}
              defaultOpen={index === 0}
            />
          ))}
          {shown.length > visible ? (
            <div className="border-t border-line pt-4">
              <Button onClick={() => setVisible((count) => count + PAGE_SIZE)}>
                Show {Math.min(PAGE_SIZE, shown.length - visible)} older runs
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function RunBlock({
  run,
  job,
  agentId,
  ruleText,
  defaultOpen,
}: {
  run: RunSummary;
  job: RunJob | null | undefined;
  agentId: string;
  ruleText: Record<string, string>;
  defaultOpen: boolean;
}) {
  const drifted = run.tasks.filter((t) => t.drift_kind).length;
  const stable = run.tasks.filter((t) => t.passed_by_trial.every(Boolean)).length;
  const state = runState(run, job);
  const [expanded, setExpanded] = useState(defaultOpen);

  return (
    <section aria-label={`${run.run_id}, ${state.label}`} className="border-b border-line">
      <header className="flex flex-wrap items-end justify-between gap-4 pb-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <Pill tone={state.tone}>{state.label}</Pill>
          <Pill tone={run.split === "train" ? "train" : "holdout"}>{run.split}</Pill>
          <span className="text-[12px] text-fg">v{run.version}</span>
          <span className="text-[11px] text-fg-mute">{run.run_id}</span>
          <span className="text-[11px] text-fg-mute">
            {run.trials} {run.trials === 1 ? "trial" : "trials"} · {run.tasks.length}{" "}
            recorded tasks
          </span>
          <span className="basis-full text-[10px] text-fg-mute">
            started {shortTs(run.started_ts ?? undefined)} · finished{" "}
            {shortTs(run.finished_ts ?? undefined)}
          </span>
        </div>
        <div className="flex flex-wrap items-end gap-6">
          <Stat
            label="pass@1"
            value={pct(run.pass_at_1)}
            tone={run.split === "train" ? "train" : "holdout"}
            size="md"
          />
          <Stat
            label="pass^k"
            value={pct(run.pass_pow_k)}
            tone={run.split === "train" ? "train" : "holdout"}
            size="md"
          />
          <Stat
            label="stable"
            value={run.tasks.length > 0 ? `${stable}/${run.tasks.length}` : "—"}
            size="md"
          />
          <Stat label="cost" value={usd(run.total_cost_usd)} size="md" />
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
            className="border border-line px-3 py-2 font-mono text-[10px] font-bold uppercase tracking-[0.06em] text-[#ff563c] hover:border-[#ff9783] hover:text-[#ff9783]"
          >
            {expanded ? "hide results ↑" : "view results ↓"}
          </button>
        </div>
      </header>

      {expanded ? (
        <div>
          {state.note ? (
            <p
              className={`border-t border-line-soft py-2 text-[11px] leading-5 ${state.label === "failed" ? "text-fail" : "text-fg-mute"}`}
            >
              {state.note}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-6 border-t border-line-soft py-3">
            <Stat
              label="p50 / p95 latency"
              value={`${ms(run.p50_latency_ms)} / ${ms(run.p95_latency_ms)}`}
              size="md"
            />
            <Stat
              label="drifted tasks"
              value={String(drifted)}
              tone={drifted > 0 ? "drift" : undefined}
              size="md"
            />
          </div>

          {run.tasks.length === 0 ? (
            <p className="border-t border-line-soft py-4 text-[11px] text-fg-mute">
              No task results were recorded for this run.
            </p>
          ) : (
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
                {run.tasks.map((t) => (
                  <TaskRow
                    key={t.case_id}
                    run={run}
                    task={t}
                    agentId={agentId}
                    ruleText={ruleText}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}
    </section>
  );
}

function TaskRow({
  run,
  task,
  agentId,
  ruleText,
}: {
  run: RunSummary;
  task: TaskResult;
  agentId: string;
  ruleText: Record<string, string>;
}) {
  const failed = task.passed_by_trial.some((p) => !p);

  return (
    <tr>
      <Td>
        <Link
          href={`/agents/${agentId}/compare?case_id=${encodeURIComponent(task.case_id)}`}
          className="text-fg hover:text-[#ff9783] hover:underline"
          title="Compare v0 and the current version on this task"
        >
          {task.case_id}
        </Link>
      </Td>
      <Td>
        <PassStrip passed={task.passed_by_trial} />
        {failed ? <GraderDisagreeButton /> : null}
      </Td>
      <Td className="text-right tabular-nums text-fg-dim">{num(task.score, 2)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{usd(task.cost_usd)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{ms(task.latency_ms)}</Td>
      <Td className="text-right tabular-nums text-fg-dim">{task.tool_calls}</Td>
      <Td className={`text-right tabular-nums ${task.tool_errors > 0 ? "text-fail" : "text-fg-mute"}`}>
        {task.tool_errors}
      </Td>
      <Td>
        {task.rules_injected.length === 0 ? (
          <span className="text-fg-mute">—</span>
        ) : (
          <span
            className="cursor-help text-fg-dim underline decoration-dotted underline-offset-2"
            title={task.rules_injected
              .map((id) => `${id}: ${ruleText[id] ?? "(text not in this version)"}`)
              .join("\n\n")}
          >
            {task.rules_injected.length} injected
          </span>
        )}
      </Td>
      <Td>{task.drift_kind ? <DriftBadge kind={task.drift_kind} /> : null}</Td>
      <Td className="text-[11px]">
        {task.trace_url ? (
          <a
            href={task.trace_url}
            target="_blank"
            rel="noreferrer"
            className="text-[#ff563c] hover:text-[#ff9783]"
          >
            trace
          </a>
        ) : null}
        {task.trace_url && task.transcript_path ? <span className="text-fg-mute"> · </span> : null}
        {task.transcript_path ? (
          <span
            className="text-fg-mute"
            title={`${task.transcript_path} · no transcript download endpoint is available in this build`}
          >
            transcript recorded
          </span>
        ) : null}
        {!task.trace_url && !task.transcript_path ? (
          <span className="text-fg-mute">— unavailable</span>
        ) : null}
      </Td>
    </tr>
  );
}

function runTime(run: RunSummary): number {
  const parsed = Date.parse(run.finished_ts ?? run.started_ts ?? "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

function runState(run: RunSummary, job: RunJob | null | undefined): {
  label: "queued" | "running" | "completed" | "failed" | "status unavailable";
  tone: "quiet" | "train" | "pass" | "fail";
  note?: string;
} {
  if (run.finished_ts) return { label: "completed", tone: "pass" };
  if (job?.status === "error") {
    return {
      label: "failed",
      tone: "fail",
      note: job.error
        ? `Failure report: ${job.error}. Partial task results are kept below when available.`
        : "This run failed without a recorded error message. Partial task results are kept below when available.",
    };
  }
  if (job?.status === "done") {
    return {
      label: "completed",
      tone: "pass",
      note: "The job completed, but no final run report was recorded. Partial task results are shown below when available.",
    };
  }
  if (job?.status === "queued") {
    return {
      label: "queued",
      tone: "quiet",
      note: "Waiting to start; no final report is available yet.",
    };
  }
  if (job?.status === "running") {
    return {
      label: "running",
      tone: "train",
      note: "Currently running; recorded task results may be partial.",
    };
  }
  if (job === undefined) {
    return { label: "status unavailable", tone: "quiet", note: "Checking persisted job status…" };
  }
  return {
    label: "status unavailable",
    tone: "quiet",
    note: "This run has no final report and its persisted job status is unavailable. It may be a legacy or interrupted run.",
  };
}

function useUnfinishedRunJobs(runs: RunSummary[], onTerminal: () => void): RunJobs {
  const [jobs, setJobs] = useState<RunJobs>({});
  const unfinishedIds = useMemo(
    () => runs.filter((run) => !run.finished_ts).map((run) => run.run_id),
    [runs],
  );
  const ids = useMemo(() => unfinishedIds.slice(0, MAX_STATUS_LOOKUPS), [unfinishedIds]);
  const key = ids.join("\n");

  useEffect(() => {
    if (ids.length === 0) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      const entries = await Promise.all(
        ids.map(async (id): Promise<[string, RunJob | null]> => {
          try {
            const job = await getJob(id);
            return [id, { status: job.status, error: job.error }];
          } catch {
            return [id, null];
          }
        }),
      );
      if (cancelled) return;
      const next = Object.fromEntries(entries) as RunJobs;
      setJobs(next);
      if (entries.some(([, job]) => job?.status === "done" || job?.status === "error")) {
        onTerminal();
      }
      if (entries.some(([, job]) => job?.status === "queued" || job?.status === "running")) {
        timer = setTimeout(refresh, ACTIVE_POLL_MS);
      }
    }

    void refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // `key` is a stable signature for the bounded id list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return Object.fromEntries(
    unfinishedIds.map((id) => [id, ids.includes(id) ? jobs[id] : null]),
  );
}

function GraderDisagreeButton() {
  return (
    <button
      type="button"
      disabled
      title="Grader review filing is unavailable in this build"
      className="ml-2 cursor-not-allowed text-[10px] text-fg-mute opacity-60"
    >
      grader disagreed? · unavailable in this build
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
          className={`border px-2 py-1 font-mono text-[10px] ${
            value === opt
              ? "border-fg bg-fg text-ink-900"
              : "border-transparent text-fg-mute hover:text-[#ff9783]"
          }`}
        >
          {format(opt)}
        </button>
      ))}
    </span>
  );
}
