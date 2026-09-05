/**
 * Wire types for the Task Orchestrator REST API.
 *
 * Source of truth: PLAN.md section 4.5, plus the additions frozen by the
 * orchestrator in sections 0.2-0.4 (compare endpoint, runs endpoint, jobs
 * endpoint, memory growth + tool efficiency insight series, memory fix cards,
 * text-only issues).
 *
 * contracts/api.md does not exist on this branch yet (Phase 0 had not merged
 * when this workstream started). When it lands these types are reconciled
 * against it; mismatches are reported, not silently changed.
 */

/* ------------------------------------------------------------------ common */

export type Split = "train" | "holdout";
export type Lever = "prompt" | "tools" | "memory" | "orchestration" | "routing";
export type Orchestration = "single" | "planner_worker" | "generate_critic";
export type DriftKind = "loop" | "budget" | "off_task" | "step_limit";

/** A pass rate is never a bare number: it always carries its spread. */
export interface PassRate {
  mean: number;
  std: number;
  min: number;
  max: number;
}

export type Json = Record<string, unknown>;

/* ------------------------------------------------------------------ memory */

/** agents/<id>/v<N>/memory/rules.jsonl (PLAN.md 0.2) */
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
  demoted?: boolean;
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

/** agents/<id>/v<N>/memory/episodes.jsonl - one line per run. */
export interface Episode {
  id: string;
  text: string;
  created_version?: number;
  run_id?: string;
  ts?: string;
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
  /** kind=episode, or any free-text form */
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
  latest_train: PassRate | null;
  latest_holdout: PassRate | null;
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
  case_counts: { train: number; holdout: number };
}

/* -------------------------------------------------------------------- runs */

/** One case inside a run, aggregated over its repeats. */
export interface CaseRow {
  case_id: string;
  /** One entry per repeat, in repeat order. */
  passed_by_repeat: boolean[];
  score: number;
  cost_usd: number;
  latency_ms: number;
  tool_calls: number;
  tool_errors: number;
  rules_injected: string[];
  transcript_path: string;
  trace_url?: string;
  /** Set when any repeat of this case tripped the drift watchdog. */
  drift_kind?: DriftKind;
}

/** GET /agents/{id}/runs */
export interface RunSummary {
  run_id: string;
  version: number;
  split: Split;
  repeats: number;
  pass_rate: PassRate;
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

export interface FixBefore {
  train_mean: number | null;
  train_std: number | null;
  group_pass: number | null;
  cost_per_run: number | null;
}

export interface FixAfter extends FixBefore {
  holdout_mean: number | null;
  holdout_std: number | null;
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
  diff_summary: string;
  files_touched: string[];
  diff_url: string;
  before: FixBefore;
  after: FixAfter;
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
}

/** Issues are text-only: screenshot upload was dropped in PLAN.md 0.4. */
export interface CreateIssueRequest {
  agent_id: string;
  title: string;
  body: string;
}

/* ---------------------------------------------------------------- insights */

export interface PassRatePoint extends PassRate {
  version: number;
  split: Split;
}

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

/** PLAN.md 0.3: memory growth. */
export interface MemoryGrowthPoint {
  version: number;
  rules: number;
  tool_notes: number;
  mean_confidence: number | null;
  demotions: number;
}

/** PLAN.md 0.3: tool-usage efficiency. All of these are expected to fall. */
export interface ToolEfficiencyPoint {
  version: number;
  split: Split;
  tool_calls_per_case: number;
  tool_errors_per_case: number;
  tokens_per_case: number;
  latency_ms_per_case: number;
}

export interface DriftStats {
  count_by_kind: Partial<Record<DriftKind, number>>;
  tokens_saved: number;
  cases_recovered_by_nudge: number;
  count_by_version?: { version: number; count: number }[];
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
  repeats: number;
  pass_rate_by_version: PassRatePoint[];
  cost_by_version: CostPoint[];
  latency_by_version: LatencyPoint[];
  fixes_by_lever: Partial<Record<Lever, number>>;
  regressions_caught: number;
  issues: { open: number; closed: number };
  lessons_count: number;
  drift: DriftStats;
  markers: Marker[];
  memory_growth_by_version: MemoryGrowthPoint[];
  tool_efficiency_by_version: ToolEfficiencyPoint[];
}

export interface AblationReport {
  domain: string;
  playbook_off: { agent_id: string; holdout: PassRate };
  playbook_on: { agent_id: string; holdout: PassRate };
  applied_lesson_ids: string[];
}

/** GET /insights/compare */
export interface InsightsCompare {
  domains: {
    agent_id: string;
    name: string;
    domain: string;
    pass_rate_by_version: PassRatePoint[];
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
