"use client";

import { useEffect, useMemo, useState } from "react";
import RunTaskList from "@/components/agent/RunTaskList";
import Stat from "@/components/Stat";
import { Empty, Pill } from "@/components/ui";
import { getJob } from "@/lib/api";
import { pct, shortTs } from "@/lib/format";
import type { Job, RunSummary } from "@/lib/types";

const DEFAULT_RUN_COUNT = 3;
const MAX_STATUS_LOOKUPS = 20;
const ACTIVE_POLL_MS = 2_000;

type RunJob = Pick<Job, "status" | "error">;
type RunJobs = Record<string, RunJob | null | undefined>;

/** Recent persisted evaluation history, with task detail kept inside each run. */
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
  const [showAll, setShowAll] = useState(false);
  const jobs = useUnfinishedRunJobs(runs, onTerminal);

  const newestFirst = useMemo(
    () => runs.slice().sort((a, b) => runTime(b) - runTime(a)),
    [runs],
  );
  const shown = showAll ? newestFirst : newestFirst.slice(0, DEFAULT_RUN_COUNT);
  const canToggle = runs.length > DEFAULT_RUN_COUNT;

  if (runs.length === 0) {
    return (
      <Empty>
        No run history yet. Press <b className="text-fg">Run train</b> to evaluate this version
        against the train split, or <b className="text-fg">Run holdout</b> for the split the
        improver never sees.
      </Empty>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
        <div>
          <h2 className="text-[13px] font-medium text-fg">Run history</h2>
          <p className="mt-1 text-[11px] text-fg-mute">
            Showing {shown.length} of {runs.length} {runs.length === 1 ? "run" : "runs"}, newest
            first
          </p>
        </div>
        {canToggle ? (
          <button
            type="button"
            onClick={() => setShowAll((value) => !value)}
            className="border border-line px-3 py-2 font-mono text-[10px] text-fg-dim hover:border-fg-dim hover:text-fg"
          >
            {showAll ? "Show fewer" : `Show all ${runs.length}`}
          </button>
        ) : null}
      </div>

      <div className="space-y-6">
        {shown.map((run) => (
          <RunBlock
            key={run.run_id}
            run={run}
            job={jobs[run.run_id]}
            agentId={agentId}
            ruleText={ruleText}
          />
        ))}
      </div>
    </div>
  );
}

function RunBlock({
  run,
  job,
  agentId,
  ruleText,
}: {
  run: RunSummary;
  job: RunJob | null | undefined;
  agentId: string;
  ruleText: Record<string, string>;
}) {
  const drifted = run.tasks.filter((task) => task.drift_kind).length;
  const stable = run.tasks.filter((task) => task.passed_by_trial.every(Boolean)).length;
  const state = runState(run, job);

  return (
    <section aria-label={`${run.run_id}, ${state.label}`} className="border border-line p-5 sm:p-6">
      <header className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <Pill tone={state.tone}>{state.label}</Pill>
            <Pill tone={run.split === "train" ? "train" : "holdout"}>{run.split}</Pill>
            <span className="text-[12px] text-fg">Version {run.version}</span>
          </div>
          <p className="mt-3 text-[11px] leading-5 text-fg-mute">
            {run.tasks.length} {run.tasks.length === 1 ? "task" : "tasks"} · {run.trials}{" "}
            {run.trials === 1 ? "trial" : "trials"} · started{" "}
            {shortTs(run.started_ts ?? undefined)} · finished {shortTs(run.finished_ts ?? undefined)}
          </p>
          <details className="mt-2 text-[10px] text-fg-mute">
            <summary className="w-fit cursor-pointer hover:text-fg-dim">Run details</summary>
            <p className="mt-2 break-all font-mono">{run.run_id}</p>
          </details>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-4">
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
          {drifted > 0 ? (
            <Stat label="drift" value={String(drifted)} tone="drift" size="md" />
          ) : null}
        </div>
      </header>

      {state.note ? (
        <p
          className={`mt-5 border-t border-line-soft pt-4 text-[11px] leading-5 ${state.label === "failed" ? "text-fail" : "text-fg-mute"}`}
        >
          {state.note}
        </p>
      ) : null}

      <details className="mt-6 border-t border-line pt-5">
        <summary className="w-fit cursor-pointer text-[11px] text-fg-dim hover:text-fg">
          View task results ({run.tasks.length})
        </summary>
        <div className="mt-5">
          {run.tasks.length > 0 ? (
            <RunTaskList run={run} agentId={agentId} ruleText={ruleText} />
          ) : (
            <p className="text-[11px] text-fg-mute">No task results have been recorded yet.</p>
          )}
        </div>
      </details>
    </section>
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
    return { label: "queued", tone: "quiet", note: "Waiting to start." };
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
    note: "This run has no final report and its persisted job status is unavailable.",
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
