/**
 * Wire types for the Task Orchestrator REST API.
 *
 * Source of truth: `contracts/api.md` (frozen after Phase 0), cross-checked
 * against `contracts/events.py`, `contracts/agent_package.md`,
 * `contracts/evaluator.md` and `contracts/playbook.md` where api.md is silent
 * on a shape. Where api.md is genuinely silent (the exact `GET /evaluators`
 * and `GET /events` row shapes, most of `GET /agents/{id}`), the type below
 * is this workstream's reasonable inference, not a contract quote.
 *
 * Terminology (contract section J): a `case` in the JSON is called a **task**
 * in prose and UI; a `repeat` is a **trial**; `score.py` is the **grader**.
 * Field names below keep the contract's wire names (`case_id`,
 * `passed_by_trial`, ...) even where the UI says "task".
 *
 * Flat floats vs. RateStat (events.py's own boundary, restated here): ledger
 * events and anything that is a direct read of one (`FixCard.before/after`,
 * `RunSummary`) use flat float fields, because an event is one observed fact.
 * `RateStat` (mean/std/min/max) exists only on the `/insights` per-version
 * chart series, where the caller wants spread bundled with the mean.
 */

/* ------------------------------------------------------------------ common */

export type Split = "train" | "holdout";
export type Lever = "prompt" | "tools" | "memory" | "orchestration" | "routing" | "grader";
/** `generate_critic` was dropped (PLAN.md 0.4); do not add it back without a contract change. */
export type Orchestration = "single" | "planner_worker";
export type DriftKind = "loop" | "budget" | "off_task" | "step_limit";

/**
 * The return shape of W1's `pass_at_1()` / `pass_pow_k()` metric functions and
 * the `/insights` chart series only. pass@1 = mean per-trial pass rate over
 * tasks. pass^k (k = trials) = fraction of tasks that passed every trial (the
 * stable pass set). Never call either one "accuracy".
 */
export interface RateStat {
  mean: number;
  std: number;
  min: number;
  max: number;
}

/** VersionPoint in contracts/api.md: one point on a pass@1 / pass^k chart. */
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

/** agents/<id>/v<N>/memory/rules.jsonl (contracts/agent_package.md) */
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

/** A memory entry as carried on a lever=memory fix card (this workstream's UI shape, not a contract type). */
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

/** GET /agents. Exact row shape is this workstream's inference (api.md does not detail it). */
export interface AgentSummary {
  agent_id: string;
  name: string;
  goal: string;
  domain: string;
  evaluator_id: string;
  current_version: number;
  created_ts: string;
  /** Latest recorded run's pass@1 for the current version; null when never run. */
  latest_train: RateStat | null;
  latest_holdout: RateStat | null;
}

/**
 * GET /agents/{id} and GET /agents/{id}/versions/{n}. Field list beyond the
 * agents row is this workstream's inference: agent.yaml's fields
 * (contracts/agent_package.md) plus prompt, tools and memory for the version.
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

/** GET /evaluators. Row shape is this workstream's inference. */
export interface Evaluator {
  evaluator_id: string;
  domain: string;
  description: string;
  /** The tools an agent for this evaluator is allowed to use. */
  allowed_tools: string[];
  case_counts: { train: number; holdout: number };
}

/* -------------------------------------------------------------------- runs */

/**
 * TaskResult (contracts/api.md): one task's row inside a run. Only
 * `passed_by_trial` is genuinely per-trial; every other field is taken from
 * trial 0 of that task in this run.
 */
export interface TaskResult {
  case_id: string;
  /** length == trials */
  passed_by_trial: boolean[];
  score: number;
  cost_usd: number;
  latency_ms: number;
  tool_calls: number;
  tool_errors: number;
  rules_injected: string[];
  transcript_path: string;
  trace_url?: string;
  drift_kind?: DriftKind;
}

/** RunSummary (contracts/api.md). GET /agents/{id}/runs -> RunSummary[]. */
export interface RunSummary {
  run_id: string;
  agent_id: string;
  version: number;
  split: Split;
  trials: number;
  started_ts: string;
  finished_ts?: string;
  pass_at_1: number;
  pass_pow_k: number;
  total_cost_usd: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  drift_count: number;
  tasks: TaskResult[];
}

export interface RunRequest {
  split: Split;
}

export interface RunResponse {
  run_id: string;
}

/* ----------------------------------------------------------------- compare */

/** CompareSide (contracts/api.md). `rules_injected` is a list of MemoryRule.id, not objects. */
export interface CompareSide {
  output: Json;
  rules_injected: string[];
  tool_calls: number;
  tokens: number;
}

/** Compare (contracts/api.md). GET /agents/{id}/compare?case_id= */
export interface CompareResult {
  expected: Json;
  v0: CompareSide | null;
  current: CompareSide | null;
}

/* --------------------------------------------------------------- fix cards */

export interface FailingGroup {
  signature: string;
  tag: string;
  count: number;
  case_ids: string[];
}

/**
 * fix_accepted/fix_rejected are flat floats (contracts/events.py), and
 * FixCard.before/after mirror those field names exactly (contracts/api.md).
 * No nested spread here by design.
 */
export interface FixMetrics {
  pass_at_1: number | null;
  pass_pow_k: number | null;
  group_pass: number | null;
  cost_per_run: number | null;
  tool_calls_per_task: number | null;
}

/** On a rejected card, only pass_at_1 is set; every other field is null. */
export interface FixAfterMetrics extends FixMetrics {
  holdout_pass_at_1: number | null;
  holdout_pass_pow_k: number | null;
}

/** GET /agents/{id}/fixes -> FixCard[] */
export interface FixCard {
  to_version: number;
  from_version: number;
  lever: Lever;
  status: "accepted" | "rejected";
  failing_group: FailingGroup;
  hypothesis: string;
  diagnosis: string;
  /** Set only for lever=tools fixes (the tracked-metric heuristic behind the diagnosis, section K); null otherwise. */
  metric_signal?: string | null;
  /** For lever=memory, describes the entries added/changed rather than a text diff. */
  diff_summary: string;
  files_touched: string[];
  diff_url: string;
  before: FixMetrics;
  after: FixAfterMetrics;
  /** Only on rejected cards. */
  regressed_case_ids?: string[];
  reason?: "regression" | "no_gain" | "error";
  /** Only on lever=memory cards: shown instead of a text diff. Not a contract field. */
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

/** GET /issues, GET /issues/{id}. Row shape beyond the create request is this workstream's inference. */
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

/**
 * POST /issues {agent_id, title, body, tags?[]} (contracts/api.md). Plain
 * JSON, not multipart — issues are text-only. The "grader disagreed?" path
 * sends tags: ["grader-bug"]; the task id it concerns goes in the body text,
 * not a separate field.
 */
export interface CreateIssueRequest {
  agent_id: string;
  title: string;
  body: string;
  tags?: string[];
}

/* ---------------------------------------------------------------- insights */

/** cost_by_version (contracts/api.md): no split, no total — cost_per_run only. */
export interface CostPoint {
  version: number;
  cost_per_run: number;
}

/** latency_by_version (contracts/api.md). */
export interface LatencyPoint {
  version: number;
  p50_ms: number;
  p95_ms: number;
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
 * tool_stats_by_version (contracts/api.md, section K heuristics): calls,
 * errors, redundant calls (same tool + identical normalized args within one
 * trial), tool-response tokens and latency, per task for that version/split.
 * All expected to fall as fixes land.
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

/** drift (contracts/api.md): no per-version breakdown on this endpoint. */
export interface DriftStats {
  count_by_kind: Partial<Record<DriftKind, number>>;
  tokens_saved: number;
  cases_recovered_by_nudge: number;
}

/** Marker (contracts/api.md): chart annotation, no derived label. */
export interface Marker {
  version: number;
  ts: string;
  kind: "issue_opened" | "fix_accepted" | "fix_rejected" | "drift_detected";
  lever?: Lever;
  diagnosis?: string;
}

/** GET /insights/{agent_id} -> Insights (contracts/api.md). */
export interface Insights {
  pass_at_1_by_version: RatePoint[];
  pass_pow_k_by_version: RatePoint[];
  cost_by_version: CostPoint[];
  latency_by_version: LatencyPoint[];
  fixes_by_lever: Partial<Record<Lever, number>>;
  regressions_caught: number;
  issues: { open: number; closed: number };
  lessons_count: number;
  memory_by_version: MemoryByVersionPoint[];
  tool_stats_by_version: ToolStatsByVersionPoint[];
  drift: DriftStats;
  /** Running total of task_graduated events. */
  graduated_count: number;
  /** True once train pass@1 >= 0.95 for two consecutive versions. */
  saturated: boolean;
  /** case_ids stuck at 0% for the last 3 versions. */
  flagged_tasks: string[];
  markers: Marker[];
}

export interface AblationReport {
  domain: string;
  playbook_off: { agent_id: string; holdout: RateStat };
  playbook_on: { agent_id: string; holdout: RateStat };
  applied_lesson_ids: string[];
}

/**
 * GET /insights/compare -> per-domain series + reports/ablation.json if
 * present. Exact shape is this workstream's inference (api.md gives only the
 * one-line description).
 */
export interface InsightsCompare {
  domains: {
    agent_id: string;
    name: string;
    domain: string;
    pass_at_1_by_version: RatePoint[];
  }[];
  ablation: AblationReport | null;
}

/* ---------------------------------------------------- playbook and events */

/** playbook/lessons.jsonl row (contracts/playbook.md). GET /playbook returns these as-is. */
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

/** GET /events?agent_id=&kind=&since=. Row shape is this workstream's inference over the events table. */
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
