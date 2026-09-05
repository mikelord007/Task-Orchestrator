import type { RatePoint, RunSummary, Split, TaskResult } from "../types";

/**
 * pass@1 and pass^k, applied to mock data so the fixtures cannot disagree with
 * themselves (contracts/events.py section on pass@1/pass^k): pass@1 mean is
 * the mean over tasks of passes/trials. pass^k is the fraction of tasks that
 * passed every trial (the stable pass set). RunSummary stores both as flat
 * floats (mean only) per the contract; std/min/max only exist on the
 * `/insights` per-version chart series, computed separately in this file.
 */
export function passAt1Mean(tasks: TaskResult[], trials: number): number {
  if (tasks.length === 0) return 0;
  const mean =
    tasks.reduce((acc, t) => acc + t.passed_by_trial.filter(Boolean).length / trials, 0) /
    tasks.length;
  return round(mean);
}

/** Fraction of tasks that passed every trial: the stable pass set, as a rate. */
export function passPowKMean(tasks: TaskResult[]): number {
  if (tasks.length === 0) return 0;
  return round(stablePassSet(tasks).length / tasks.length);
}

/** Tasks that passed in every trial (the stable pass set; the gate uses pass^k). */
export function stablePassSet(tasks: TaskResult[]): string[] {
  return tasks.filter((t) => t.passed_by_trial.every(Boolean)).map((t) => t.case_id);
}

/**
 * mean/std/min/max over the per-trial run-level pass@1, for the /insights
 * chart series only (RateStat/RatePoint boundary, contracts/events.py).
 */
export function pass1RatePoint(run: RunSummary): RatePoint {
  const perTrial: number[] = [];
  for (let t = 0; t < run.trials; t++) {
    perTrial.push(run.tasks.filter((task) => task.passed_by_trial[t]).length / (run.tasks.length || 1));
  }
  const mean = perTrial.reduce((a, b) => a + b, 0) / perTrial.length;
  const std = Math.sqrt(perTrial.reduce((acc, v) => acc + (v - mean) ** 2, 0) / perTrial.length);
  return {
    version: run.version,
    split: run.split,
    mean: round(mean),
    std: round(std),
    min: round(Math.min(...perTrial)),
    max: round(Math.max(...perTrial)),
  };
}

/**
 * pass^k has no per-trial variance within one run (it is already the fraction
 * of tasks stable across all trials), so its chart point collapses mean=min=max
 * to the run's single pass^k value with std=0.
 */
export function passPowKRatePoint(run: RunSummary): RatePoint {
  return { version: run.version, split: run.split, mean: run.pass_pow_k, std: 0, min: run.pass_pow_k, max: run.pass_pow_k };
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}

function round(n: number): number {
  return Math.round(n * 10000) / 10000;
}

export function makeRun(args: {
  run_id: string;
  agent_id: string;
  version: number;
  split: Split;
  trials: number;
  started_ts: string;
  finished_ts: string;
  tasks: TaskResult[];
}): RunSummary {
  const latencies = args.tasks.map((t) => t.latency_ms).sort((a, b) => a - b);
  const drift_count = args.tasks.filter((t) => t.drift_kind).length;
  return {
    run_id: args.run_id,
    agent_id: args.agent_id,
    version: args.version,
    split: args.split,
    trials: args.trials,
    pass_at_1: passAt1Mean(args.tasks, args.trials),
    pass_pow_k: passPowKMean(args.tasks),
    total_cost_usd: round(args.tasks.reduce((acc, t) => acc + t.cost_usd, 0)),
    p50_latency_ms: percentile(latencies, 50),
    p95_latency_ms: percentile(latencies, 95),
    drift_count,
    started_ts: args.started_ts,
    finished_ts: args.finished_ts,
    tasks: args.tasks,
  };
}

/**
 * Compact task-row builder. `pattern` is one character per trial: x = passed,
 * . = failed. Everything else has a plausible default so the fixtures stay
 * readable.
 */
export function row(
  case_id: string,
  pattern: string,
  extra: Partial<Omit<TaskResult, "case_id" | "passed_by_trial">> = {},
): TaskResult {
  const passed_by_trial = [...pattern].map((ch) => ch === "x");
  const passes = passed_by_trial.filter(Boolean).length;
  return {
    case_id,
    passed_by_trial,
    score: extra.score ?? round(0.35 + 0.6 * (passes / passed_by_trial.length)),
    cost_usd: extra.cost_usd ?? 0.03,
    latency_ms: extra.latency_ms ?? 9000,
    tool_calls: extra.tool_calls ?? 6,
    tool_errors: extra.tool_errors ?? 0,
    rules_injected: extra.rules_injected ?? [],
    transcript_path: extra.transcript_path ?? `runs/${case_id}.t0.json`,
    trace_url: extra.trace_url,
    drift_kind: extra.drift_kind,
  };
}

/**
 * task_graduated per contracts/events.py: a task newly in the stable pass set
 * this version that was not in the prior version's. For the first train run,
 * every stable task graduates. Runs must be the train-split history sorted
 * ascending by version.
 */
export function graduatedCount(trainRunsAscending: RunSummary[]): number {
  let previous = new Set<string>();
  let total = 0;
  for (const run of trainRunsAscending) {
    const stable = new Set(stablePassSet(run.tasks));
    for (const id of stable) if (!previous.has(id)) total += 1;
    previous = stable;
  }
  return total;
}

/** Train pass@1 >= 95% for two consecutive versions (contracts/api.md). */
export function isSaturated(trainRunsAscending: RunSummary[]): boolean {
  for (let i = 1; i < trainRunsAscending.length; i++) {
    if (trainRunsAscending[i - 1].pass_at_1 >= 0.95 && trainRunsAscending[i].pass_at_1 >= 0.95) {
      return true;
    }
  }
  return false;
}

/**
 * case_ids at 0% across the last 3 train versions ("usually a broken task, not
 * an incapable agent"). Empty when fewer than 3 train runs exist yet.
 */
export function flaggedTasks(trainRunsAscending: RunSummary[]): string[] {
  if (trainRunsAscending.length < 3) return [];
  const lastThree = trainRunsAscending.slice(-3);
  const ids = new Set(lastThree[0].tasks.map((t) => t.case_id));
  const flagged: string[] = [];
  for (const id of ids) {
    let allZero = true;
    for (const run of lastThree) {
      const t = run.tasks.find((task) => task.case_id === id);
      if (!t || t.passed_by_trial.some(Boolean)) {
        allZero = false;
        break;
      }
    }
    if (allZero) flagged.push(id);
  }
  return flagged;
}
