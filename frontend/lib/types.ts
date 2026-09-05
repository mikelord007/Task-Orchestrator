/**
 * Wire types for the Task Orchestrator REST API.
 *
 * Source of truth: PLAN_ADDENDUM.md section A (and the W5 entry in
 * addendum-deltas.md), which supersedes the pre-addendum PLAN.md section 4.5.
 *
 * Terminology (addendum J): a `case` in the JSON is called a **task** in prose
 * and UI; a `repeat` is a **trial**; `score.py` is the **grader**. Field names
 * below keep the contract's wire names (`case_id`, `passed_by_trial`, ...)
 * even where the UI says "task".
 *
 * contracts/ does not exist on this branch yet (Phase 0 had not merged when
 * this workstream started). When it lands these types are reconciled against
 * it; mismatches are reported, not silently changed.
 */

/* ------------------------------------------------------------------ common */

export type Split = "train" | "holdout";
export type Lever = "prompt" | "tools" | "memory" | "orchestration" | "routing" | "grader";
export type Orchestration = "single" | "planner_worker" | "generate_critic";
export type DriftKind = "loop" | "budget" | "off_task" | "step_limit";

/**
 * pass@1 = mean per-trial pass rate over tasks. pass^k (k = trials) = fraction
 * of tasks that passed every trial (the stable pass set). Never call either
 * one "accuracy". mean/std/min/max are computed over the trial-level pass
 * rates; trials/task_count say what produced them.
 */
export interface RateStat {
  mean: number;
  std: number;
  min: number;
  max: number;
  trials?: number;
  task_count?: number;
}

/** One point on a pass@1 / pass^k chart. */
export interface RatePoint {
  version: number;
  split: Split;
  mean: number;
  std: number;
  min: number;
  max: number;
}

export type Json = Record<string, unknown>;

/* ------------------------------------------------------------------ memory */

/** agents/<id>/v<N>/memory/rules.jsonl (addendum section E) */
export interface MemoryRule {
  id: string;
  rule: string;
  scope_keywords: string[];
  evidence_case_ids: string[];
  confidence: number;
  hits: number;
  misses: number;
  created_version: number;
  source: "reflection" | "issue";
  /** Demoted rules stay on disk but are no longer injected. */
  demoted: boolean;
  demoted_version?: number;
}

/** agents/<id>/v<N>/memory/tool_notes.jsonl */
export interface ToolNote {
  id: string;
  tool: string;
  note: string;
  evidence: string;
  created_version: number;
}

/**
 * agents/<id>/v<N>/memory/episodes.jsonl - one line of reflection per run.
 * Contract shape is exactly {version, run_id, one_line_reflection}; there is
 * no separate id field, so the UI keys episodes on run_id.
 */
export interface Episode {
  version: number;
  run_id: string;
  one_line_reflection: string;
}

export interface AgentMemory {
  rules: MemoryRule[];
  tool_notes: ToolNote[];
  episodes: Episode[];
}

/** A memory entry as carried on a lever=memory fix card. */
export interface MemoryEntryChange {
  id: string;
  kind: "rule" | "tool_note" | "episode";
  change?: "added" | "updated" | "demoted";
  /** kind=rule */
  rule?: string;
  scope_keywords?: string[];
  confidence?: number;
  /** kind=tool_note */
  tool?: string;
  note?: string;
  /** kind=episode, or any free-text note on a change */
  text?: string;
  evidence?: string;
  evidence_case_ids?: string[];
  source?: "reflection" | "issue";
  created_version?: number;
}

/* ------------------------------------------------------------------ agents */

export interface ToolRef {
  name: string;
  description: string;
}

/** GET /agents */
export interface AgentSummary {
  agent_id: string;
  name: string;
  goal: string;
  domain: string;
  evaluator_id: string;
  current_version: number;
  created_ts: string;
  /** Latest recorded run per split for the current version; null when never run. */
  latest_train: RateStat | null;
  latest_holdout: RateStat | null;
}

/**
 * GET /agents/{id} and GET /agents/{id}/versions/{n}
 * The agents row plus the described version's agent.yaml fields, prompt,
 * tools and memory.
 */
export interface AgentDetail extends AgentSummary {
  /** The version this payload describes (= current_version for GET /agents/{id}). */
  version: number;
  model_strong: string;
  model_cheap: string;
  orchestration: Orchestration;
  routing: Record<string, "strong" | "cheap">;
  prompt: string;
  tools: ToolRef[];
  memory: AgentMemory;
  applied_lessons?: string[];
  /** Optional; falls back to 0..current_version for the version switcher. */
  versions?: number[];
}

export interface CreateAgentRequest {
  goal: string;
  domain: string;
  tools: string[];
  evaluator_id: string;
  use_playbook: boolean;
}

export interface CreateAgentResponse {
  agent_id: string;
  version: number;
}

/* --------------------------------------------------------------- evaluator */

/** GET /evaluators */
export interface Evaluator {
  evaluator_id: string;
  domain: string;
  description: string;
  /** The tools an agent for this evaluator is allowed to use. */
  allowed_tools: string[];
  /** Task counts (contract field name stays case_counts). */
  case_counts: { train: number; holdout: number };
}

/* -------------------------------------------------------------------- runs */

/** One task's row inside a run, aggregated over its trials. */
export interface CaseRow {
  case_id: string;
  /** One entry per trial, in trial order. */
  passed_by_trial: boolean[];
  score: number;
  cost_usd: number;
  latency_ms: number;
  tool_calls: number;
  tool_errors: number;
  rules_injected: string[];
  transcript_path: string;
  trace_url?: string;
  /** Set when any trial of this task tripped the drift watchdog. */
  drift_kind?: DriftKind;
}

/** GET /agents/{id}/runs */
export interface RunSummary {
  run_id: string;
  version: number;
  split: Split;
  trials: number;
  pass_at_1: RateStat;
  /** Fraction of this run's tasks that passed every trial. */
  pass_pow_k: number;
  total_cost_usd: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  started_ts?: string;
  finished_ts?: string;
  cases: CaseRow[];
}

export interface RunRequest {
  split: Split;
}

export interface RunResponse {
  run_id: string;
}

/* ----------------------------------------------------------------- compare */

export interface InjectedRule {
  id: string;
  rule?: string;
}

export interface CompareSide {
  output: Json;
  rules_injected: InjectedRule[];
  tool_calls: number;
  tokens: number;
}

/** GET /agents/{id}/compare?case_id= */
export interface CompareResult {
  case_id: string;
  expected: Json;
  v0: CompareSide | null;
  current: CompareSide | null;
  current_version?: number;
}

/* --------------------------------------------------------------- fix cards */

export interface FailingGroup {
  signature: string;
  tag: string;
  count: number;
  case_ids: string[];
}

/** fix_accepted / fix_rejected metric names, addendum section A. */
export interface FixMetrics {
  pass_at_1: number | null;
  pass_at_1_std?: number | null;
  pass_pow_k: number | null;
  group_pass: number | null;
  cost_per_run: number | null;
  tool_calls_per_task: number | null;
}

export interface FixAfterMetrics extends FixMetrics {
  holdout_pass_at_1: number | null;
  holdout_pass_at_1_std?: number | null;
  holdout_pass_pow_k: number | null;
}

/** GET /agents/{id}/fixes */
export interface FixCard {
  to_version: number;
  from_version: number;
  lever: Lever;
  status: "accepted" | "rejected";
  failing_group: FailingGroup;
  hypothesis: string;
  diagnosis: string;
  /**
   * Tools-lever diagnoses cite the tracked-metric signal that motivated the
   * change, e.g. "4.1 redundant calls/task" or "3 invalid-parameter errors".
   */
  metric_signal?: string;
  diff_summary: string;
  files_touched: string[];
  diff_url: string;
  before: FixMetrics;
  after: FixAfterMetrics;
  /** Only on rejected cards. */
  regressed_case_ids?: string[];
  reason?: "regression" | "no_gain" | "error";
  /** Only on lever=memory cards: shown instead of a text diff. */
  memory_entries?: MemoryEntryChange[];
  ts?: string;
}

/* -------------------------------------------------------------------- jobs */

export type JobStatus = "queued" | "running" | "done" | "error";

/** GET /jobs/{id} */
export interface Job {
  job_id: string;
  kind: string;
  status: JobStatus;
  progress: { done: number; total: number };
  result?: Json;
  error?: string;
}

export interface ImproveRequest {
  max_attempts: number;
  issue_id?: string;
}

export interface JobResponse {
  job_id: string;
}

/* ------------------------------------------------------------------ issues */

export type IssueSource = "human" | "auto";
export type IssueStatus = "open" | "fixing" | "fixed" | "wontfix";

export interface Issue {
  issue_id: string;
  agent_id: string;
  title: string;
  body: string;
  source: IssueSource;
  status: IssueStatus;
  failure_signature?: string;
  created_ts: string;
  fixed_version?: number;
  linked_case_ids: string[];
  /** e.g. ["grader-bug"] from the "Grader disagreed?" path. */
  tags?: string[];
}

/** Issues are text-only: screenshot upload was dropped. */
export interface CreateIssueRequest {
  agent_id: string;
  title: string;
  body: string;
  tags?: string[];
  /** The task this issue was filed from, when filed from a run row. */
  case_id?: string;
}

/* ---------------------------------------------------------------- insights */

export interface CostPoint {
  version: number;
  split: Split;
  total_cost_usd: number;
  cost_per_run_usd: number;
}

export interface LatencyPoint {
  version: number;
  split: Split;
  p50_latency_ms: number;
  p95_latency_ms: number;
}

/** memory_by_version: rules + tool notes count and mean confidence per version. */
export interface MemoryByVersionPoint {
  version: number;
  rules: number;
  tool_notes: number;
  mean_confidence: number | null;
  demotions: number;
}

/**
 * tool_stats_by_version (addendum section K): calls, errors, redundant calls
 * (same tool + identical normalized args within one trial), tool-response
 * tokens and latency, per task. All expected to fall as fixes land.
 */
export interface ToolStatsByVersionPoint {
  version: number;
  split: Split;
  calls: number;
  errors: number;
  redundant: number;
  tool_tokens: number;
  latency_ms: number;
}

export interface DriftStats {
  count_by_kind: Partial<Record<DriftKind, number>>;
  tokens_saved: number;
  cases_recovered_by_nudge: number;
  count_by_version?: { version: number; count: number }[];
}

/** A task stuck at 0% across the last 3 versions ("usually a broken task"). */
export interface FlaggedTask {
  case_id: string;
  versions_at_zero: number[];
  tag?: string;
}

export interface Marker {
  version: number;
  kind: "issue_opened" | "fix_accepted" | "fix_rejected" | "drift_detected";
  lever?: Lever;
  diagnosis?: string;
  label: string;
  to_version?: number;
  count?: number;
  ts?: string;
}

/** GET /insights/{agent_id} */
export interface Insights {
  agent_id: string;
  trials: number;
  pass_at_1_by_version: RatePoint[];
  pass_pow_k_by_version: RatePoint[];
  cost_by_version: CostPoint[];
  latency_by_version: LatencyPoint[];
  fixes_by_lever: Partial<Record<Lever, number>>;
  regressions_caught: number;
  issues: { open: number; closed: number };
  lessons_count: number;
  drift: DriftStats;
  markers: Marker[];
  memory_by_version: MemoryByVersionPoint[];
  tool_stats_by_version: ToolStatsByVersionPoint[];
  /** Tasks newly in the stable pass set this version that were not last version. */
  graduated_count: number;
  /** Train pass@1 >= 95% for two consecutive versions. */
  saturated: boolean;
  flagged_tasks: FlaggedTask[];
}

export interface AblationReport {
  domain: string;
  playbook_off: { agent_id: string; holdout: RateStat };
  playbook_on: { agent_id: string; holdout: RateStat };
  applied_lesson_ids: string[];
}

/** GET /insights/compare */
export interface InsightsCompare {
  domains: {
    agent_id: string;
    name: string;
    domain: string;
    pass_at_1_by_version: RatePoint[];
  }[];
  /** reports/ablation.json, when it exists. */
  ablation: AblationReport | null;
}

/* ---------------------------------------------------- playbook and events */

export interface Lesson {
  id: string;
  lever: Lever;
  trigger: string;
  lesson: string;
  domain_tags: string[];
  source_agent_id: string;
  source_issue_id?: string;
  ts: string;
}

/** GET /events */
export interface LedgerEvent {
  id: number;
  ts: string;
  kind: string;
  agent_id?: string;
  agent_version?: number;
  run_id?: string;
  lever?: Lever;
  payload: Json;
}

export interface EventQuery {
  agent_id?: string;
  kind?: string;
  since?: string;
}
