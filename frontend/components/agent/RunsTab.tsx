"use client";

import { useMemo, useState } from "react";
import RunTaskList from "@/components/agent/RunTaskList";
import Stat from "@/components/Stat";
import { Empty, Pill } from "@/components/ui";
import { pct, shortTs } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

const DEFAULT_RUN_COUNT = 3;

/** Recent evaluation history, with task detail kept inside each run. */
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
  const [showAll, setShowAll] = useState(false);

  const newestFirst = useMemo(
    () =>
      runs.slice().sort((a, b) => {
        const aTime = Date.parse(a.finished_ts ?? a.started_ts);
        const bTime = Date.parse(b.finished_ts ?? b.started_ts);
        return bTime - aTime;
      }),
    [runs],
  );
  const shown = showAll ? newestFirst : newestFirst.slice(0, DEFAULT_RUN_COUNT);
  const canToggle = runs.length > DEFAULT_RUN_COUNT;

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
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
        <div>
          <h2 className="text-[13px] font-medium text-fg">Run history</h2>
          <p className="mt-1 text-[11px] text-fg-mute">
            Showing {shown.length} of {runs.length} {runs.length === 1 ? "run" : "runs"}, newest first
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
          <RunBlock key={run.run_id} run={run} agentId={agentId} ruleText={ruleText} />
        ))}
      </div>
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
  const drifted = run.tasks.filter((task) => task.drift_kind).length;
  const stable = run.tasks.filter((task) => task.passed_by_trial.every(Boolean)).length;

  return (
    <section className="border border-line p-5 sm:p-6">
      <header className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <Pill tone={run.split === "train" ? "train" : "holdout"}>{run.split}</Pill>
            <span className="text-[12px] text-fg">Version {run.version}</span>
          </div>
          <p className="mt-3 text-[11px] leading-5 text-fg-mute">
            {run.tasks.length} {run.tasks.length === 1 ? "task" : "tasks"} · {run.trials}{" "}
            {run.trials === 1 ? "trial" : "trials"} · {shortTs(run.finished_ts)}
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
          <Stat label="stable" value={`${stable}/${run.tasks.length}`} size="md" />
          {drifted > 0 ? <Stat label="drift" value={String(drifted)} tone="drift" size="md" /> : null}
        </div>
      </header>

      <details className="mt-6 border-t border-line pt-5">
        <summary className="w-fit cursor-pointer text-[11px] text-fg-dim hover:text-fg">
          View task results ({run.tasks.length})
        </summary>
        <div className="mt-5">
          <RunTaskList run={run} agentId={agentId} ruleText={ruleText} />
        </div>
      </details>
    </section>
  );
}
