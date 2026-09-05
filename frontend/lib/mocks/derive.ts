import type { CaseRow, PassRate, RunSummary, Split } from "../types";

/**
 * Pass-rate definition from PLAN.md 4.1, applied to mock data so the fixtures
 * cannot disagree with themselves: mean is the mean over cases of
 * passes/repeats; std/min/max are over the per-repeat run-level pass rates.
 */
export function passRateFrom(cases: CaseRow[], repeats: number): PassRate {
  if (cases.length === 0) return { mean: 0, std: 0, min: 0, max: 0 };

  const mean =
    cases.reduce((acc, c) => acc + c.passed_by_repeat.filter(Boolean).length / repeats, 0) /
    cases.length;

  const perRepeat: number[] = [];
  for (let r = 0; r < repeats; r++) {
    perRepeat.push(cases.filter((c) => c.passed_by_repeat[r]).length / cases.length);
  }
  const rMean = perRepeat.reduce((a, b) => a + b, 0) / perRepeat.length;
  const std = Math.sqrt(
    perRepeat.reduce((acc, v) => acc + (v - rMean) ** 2, 0) / perRepeat.length,
  );

  return {
    mean: round(mean),
    std: round(std),
    min: round(Math.min(...perRepeat)),
    max: round(Math.max(...perRepeat)),
  };
}

/** Cases that passed in every repeat (PLAN.md 4.1 stable pass set). */
export function stablePassSet(cases: CaseRow[]): string[] {
  return cases.filter((c) => c.passed_by_repeat.every(Boolean)).map((c) => c.case_id);
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
  repeats: number;
  started_ts: string;
  finished_ts: string;
  cases: CaseRow[];
}): RunSummary {
  const latencies = args.cases.map((c) => c.latency_ms).sort((a, b) => a - b);
  return {
    run_id: args.run_id,
    version: args.version,
    split: args.split,
    repeats: args.repeats,
    pass_rate: passRateFrom(args.cases, args.repeats),
    total_cost_usd: round(args.cases.reduce((acc, c) => acc + c.cost_usd, 0)),
    p50_latency_ms: percentile(latencies, 50),
    p95_latency_ms: percentile(latencies, 95),
    started_ts: args.started_ts,
    finished_ts: args.finished_ts,
    cases: args.cases,
  };
}

/**
 * Compact case-row builder. `pattern` is one character per repeat: x = passed,
 * . = failed. Everything else has a plausible default so the fixtures stay
 * readable.
 */
export function row(
  case_id: string,
  pattern: string,
  extra: Partial<Omit<CaseRow, "case_id" | "passed_by_repeat">> = {},
): CaseRow {
  const passed_by_repeat = [...pattern].map((ch) => ch === "x");
  const passes = passed_by_repeat.filter(Boolean).length;
  return {
    case_id,
    passed_by_repeat,
    score: extra.score ?? round(0.35 + 0.6 * (passes / passed_by_repeat.length)),
    cost_usd: extra.cost_usd ?? 0.03,
    latency_ms: extra.latency_ms ?? 9000,
    tool_calls: extra.tool_calls ?? 6,
    tool_errors: extra.tool_errors ?? 0,
    rules_injected: extra.rules_injected ?? [],
    transcript_path: extra.transcript_path ?? `runs/${case_id}.r0.json`,
    trace_url: extra.trace_url,
    drift_kind: extra.drift_kind,
  };
}
