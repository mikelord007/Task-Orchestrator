import type { CaseRow, FlaggedTask, RateStat, RatePoint, RunSummary, Split } from "../types";

/**
 * pass@1 and pass^k, applied to mock data so the fixtures cannot disagree with
 * themselves (addendum section A/B): pass@1 mean is the mean over tasks of
 * passes/trials; std/min/max are over the per-trial run-level pass rates.
 * pass^k is the fraction of tasks that passed every trial (the stable set).
 */
export function passAt1From(cases: CaseRow[], trials: number): RateStat {
  if (cases.length === 0) return { mean: 0, std: 0, min: 0, max: 0, trials, task_count: 0 };

  const mean =
    cases.reduce((acc, c) => acc + c.passed_by_trial.filter(Boolean).length / trials, 0) /
    cases.length;

  const perTrial: number[] = [];
  for (let t = 0; t < trials; t++) {
    perTrial.push(cases.filter((c) => c.passed_by_trial[t]).length / cases.length);
  }
  const tMean = perTrial.reduce((a, b) => a + b, 0) / perTrial.length;
  const std = Math.sqrt(perTrial.reduce((acc, v) => acc + (v - tMean) ** 2, 0) / perTrial.length);

  return {
    mean: round(mean),
    std: round(std),
    min: round(Math.min(...perTrial)),
    max: round(Math.max(...perTrial)),
    trials,
    task_count: cases.length,
  };
}

/** Fraction of tasks that passed every trial: the stable pass set, as a rate. */
export function passPowKFrom(cases: CaseRow[]): number {
  if (cases.length === 0) return 0;
  return round(stablePassSet(cases).length / cases.length);
}

/** Tasks that passed in every trial (addendum section B: the stable pass set). */
export function stablePassSet(cases: CaseRow[]): string[] {
  return cases.filter((c) => c.passed_by_trial.every(Boolean)).map((c) => c.case_id);
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
  version: number;
  split: Split;
  trials: number;
  started_ts: string;
  finished_ts: string;
  cases: CaseRow[];
}): RunSummary {
  const latencies = args.cases.map((c) => c.latency_ms).sort((a, b) => a - b);
  return {
    run_id: args.run_id,
    version: args.version,
    split: args.split,
    trials: args.trials,
    pass_at_1: passAt1From(args.cases, args.trials),
    pass_pow_k: passPowKFrom(args.cases),
    total_cost_usd: round(args.cases.reduce((acc, c) => acc + c.cost_usd, 0)),
    p50_latency_ms: percentile(latencies, 50),
    p95_latency_ms: percentile(latencies, 95),
    started_ts: args.started_ts,
    finished_ts: args.finished_ts,
    cases: args.cases,
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
  extra: Partial<Omit<CaseRow, "case_id" | "passed_by_trial">> = {},
): CaseRow {
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

/** A pass@1 or pass^k chart point from one run, at the shape Insights wants. */
export function toRatePoint(run: RunSummary, stat: RateStat): RatePoint {
  return { version: run.version, split: run.split, mean: stat.mean, std: stat.std, min: stat.min, max: stat.max };
}

/**
 * pass^k has no per-trial variance within one run (it is already the fraction
 * of tasks stable across all trials), so its chart point collapses mean=min=max
 * to the run's single pass^k value with std=0.
 */
export function passPowKPoint(run: RunSummary): RatePoint {
  return { version: run.version, split: run.split, mean: run.pass_pow_k, std: 0, min: run.pass_pow_k, max: run.pass_pow_k };
}

/**
 * task_graduated per addendum section J/L: a task newly in the stable pass set
 * this version that was not in the prior version's stable pass set. For the
 * first train run, every stable task graduates. Runs must be sorted ascending
 * by version and be the train-split history in order.
 */
export function graduatedCount(trainRunsAscending: RunSummary[]): number {
  let previous = new Set<string>();
  let total = 0;
  for (const run of trainRunsAscending) {
    const stable = new Set(stablePassSet(run.cases));
    for (const id of stable) if (!previous.has(id)) total += 1;
    previous = stable;
  }
  return total;
}

/** Train pass@1 >= 95% for two consecutive versions (addendum section J). */
export function isSaturated(trainRunsAscending: RunSummary[]): boolean {
  for (let i = 1; i < trainRunsAscending.length; i++) {
    if (trainRunsAscending[i - 1].pass_at_1.mean >= 0.95 && trainRunsAscending[i].pass_at_1.mean >= 0.95) {
      return true;
    }
  }
  return false;
}

/**
 * Tasks at 0% across the last 3 train versions ("usually a broken task, not
 * an incapable agent"). Empty when fewer than 3 train runs exist yet.
 */
export function flaggedTasks(trainRunsAscending: RunSummary[]): FlaggedTask[] {
  if (trainRunsAscending.length < 3) return [];
  const lastThree = trainRunsAscending.slice(-3);
  const ids = new Set(lastThree[0].cases.map((c) => c.case_id));
  const flagged: FlaggedTask[] = [];
  for (const id of ids) {
    const versions: number[] = [];
    let allZero = true;
    for (const run of lastThree) {
      const c = run.cases.find((row) => row.case_id === id);
      if (!c || c.passed_by_trial.some(Boolean)) {
        allZero = false;
        break;
      }
      versions.push(run.version);
    }
    if (allZero) flagged.push({ case_id: id, versions_at_zero: versions });
  }
  return flagged;
}
