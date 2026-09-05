/**
 * Typed client for the Task Orchestrator API.
 *
 * Mirrors `contracts/api.md` exactly. The contract is frozen after Phase 0, so
 * a shape change here means a contract change there first.
 *
 * Every page fetches through this module. `NEXT_PUBLIC_USE_MOCKS=true` swaps in
 * the mock layer so the UI can be built before the backend endpoints land.
 * The Phase 0 mocks return *empty* results on purpose: no chart may ever show a
 * number that did not come from the ledger (PLAN.md §2.4).
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

// ---------------------------------------------------------------------------
// Shared types (contracts/events.py + contracts/api.md)
// ---------------------------------------------------------------------------

export type Lever =
  | "prompt"
  | "tools"
  | "memory"
  | "orchestration"
  | "routing";

export type Split = "train" | "holdout";
export type DriftKind = "loop" | "budget" | "off_task" | "step_limit";
export type Orchestration = "single" | "planner_worker";
export type JobStatus = "queued" | "running" | "done" | "error";
export type IssueSource = "human" | "auto";
export type IssueStatus = "open" | "closed";

export type PassRateStat = {
  mean: number;
  std: number;
  min?: number | null;
  max?: number | null;
};

export type Agent = {
  agent_id: string;
  goal: string;
  domain: string;
  evaluator_id: string;
  current_version: number;
  created_ts: string;
};

export type AgentVersion = {
  agent_id: string;
  version: number;
  prompt: string;
  orchestration: Orchestration;
  tools: string[];
  routing: Record<string, "strong" | "cheap">;
  memory: {
    rules: MemoryRule[];
    tool_notes: ToolNote[];
    episodes: Episode[];
  };
};

export type MemoryRule = {
  id: string;
  rule: string;
  scope_keywords: string[];
  evidence_case_ids: string[];
  confidence: number;
  hits: number;
  misses: number;
  created_version: number;
  source: "reflection" | "issue";
  demoted: boolean;
};

export type ToolNote = {
  id: string;
  tool: string;
  note: string;
  evidence: string;
  created_version: number;
};

export type Episode = {
  id: string;
  run_id: string;
  case_id: string;
  version: number;
  text: string;
};

export type LedgerEvent = {
  id: number;
  ts: string;
  kind: string;
  agent_id: string | null;
  agent_version: number | null;
  run_id: string | null;
  lever: Lever | null;
  payload: Record<string, unknown>;
};

export type FailingGroup = {
  signature: string;
  tag: string | null;
  count: number;
  case_ids: string[];
};

/** The join of one `fix_proposed` with its `fix_accepted` / `fix_rejected`. */
export type FixCard = {
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
  before: {
    train_mean: number;
    train_std: number;
    group_pass: number;
    cost_per_run: number;
  };
  after: {
    train_mean: number;
    train_std: number;
    group_pass: number | null;
    holdout_mean: number | null;
    holdout_std: number | null;
    cost_per_run: number | null;
  };
  regressed_case_ids: string[];
};

export type VersionPoint = {
  version: number;
  split: Split;
  mean: number;
  std: number;
  min: number;
  max: number;
};

export type Marker = {
  version: number;
  ts: string;
  kind: string;
  lever?: Lever | null;
  diagnosis?: string | null;
};

export type Insights = {
  pass_rate_by_version: VersionPoint[];
  cost_by_version: { version: number; cost_per_run: number }[];
  latency_by_version: { version: number; p50_ms: number; p95_ms: number }[];
  fixes_by_lever: Partial<Record<Lever, number>>;
  regressions_caught: number;
  issues: { open: number; closed: number };
  lessons_count: number;
  drift: {
    count_by_kind: Partial<Record<DriftKind, number>>;
    tokens_saved: number;
    cases_recovered_by_nudge: number;
  };
  markers: Marker[];
  /** §0.3 — memory growth per version. */
  memory_growth: {
    version: number;
    rules: number;
    tool_notes: number;
    mean_confidence: number;
    demotions: number;
  }[];
  /** §0.3 — cost/speed story: all four are expected to fall. */
  tool_efficiency: {
    version: number;
    tool_calls_per_case: number;
    tool_errors_per_case: number;
    tokens_per_case: number;
    latency_ms_per_case: number;
  }[];
};

export type CompareSide = {
  output: unknown;
  rules_injected: string[];
  tool_calls: number;
  tokens: number;
} | null;

/** §0.3 — the same case at v0 and at the current version. */
export type Compare = {
  expected: unknown;
  v0: CompareSide;
  current: CompareSide;
};

export type CompareInsights = {
  domains: {
    domain: string;
    agent_id: string;
    pass_rate_by_version: VersionPoint[];
  }[];
  ablation: Record<string, unknown> | null;
};

export type Issue = {
  id: string;
  agent_id: string;
  title: string;
  body: string;
  source: IssueSource;
  status: IssueStatus;
  failure_signature?: string | null;
  linked_case_ids: string[];
  fixed_version?: number | null;
  created_ts: string;
};

export type Job = {
  job_id: string;
  agent_id: string;
  kind: string;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  current_step?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_ts: string;
  updated_ts: string;
};

export type Lesson = {
  id: string;
  lever: Lever;
  trigger: string;
  lesson: string;
  domain_tags: string[];
  source_agent_id: string;
  source_issue_id?: string | null;
  ts: string;
};

export type Evaluator = {
  evaluator_id: string;
  domain: string;
  case_count: number;
  splits: Record<Split, number>;
  tags: string[];
};

export type CreateAgentRequest = {
  goal: string;
  domain: string;
  tools: string[];
  evaluator_id: string;
  use_playbook: boolean;
};

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly path: string,
  ) {
    super(`${status} ${path}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = ((await response.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(response.status, detail, path);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// ---------------------------------------------------------------------------
// Endpoints (contracts/api.md)
// ---------------------------------------------------------------------------

export const api = {
  createAgent: (body: CreateAgentRequest) =>
    mockOr<{ agent_id: string; version: number }>(
      () => request("/agents", { method: "POST", body: JSON.stringify(body) }),
      mocks.createAgent,
    ),

  listAgents: () => mockOr<Agent[]>(() => request("/agents"), mocks.agents),

  getAgent: (id: string) =>
    mockOr<Agent | null>(() => request(`/agents/${id}`), mocks.agent),

  getAgentVersion: (id: string, version: number) =>
    mockOr<AgentVersion | null>(
      () => request(`/agents/${id}/versions/${version}`),
      mocks.agentVersion,
    ),

  runAgent: (id: string, split: Split) =>
    mockOr<{ run_id: string }>(
      () =>
        request(`/agents/${id}/run`, {
          method: "POST",
          body: JSON.stringify({ split }),
        }),
      mocks.run,
    ),

  improveAgent: (id: string, maxAttempts = 3, issueId?: string) =>
    mockOr<{ job_id: string }>(
      () =>
        request(`/agents/${id}/improve`, {
          method: "POST",
          body: JSON.stringify({ max_attempts: maxAttempts, issue_id: issueId }),
        }),
      mocks.improve,
    ),

  getJob: (jobId: string) =>
    mockOr<Job | null>(() => request(`/jobs/${jobId}`), mocks.job),

  listIssues: (agentId?: string) =>
    mockOr<Issue[]>(
      () => request(`/issues${query({ agent_id: agentId })}`),
      mocks.issues,
    ),

  createIssue: (form: FormData) =>
    mockOr<Issue | null>(
      () => request("/issues", { method: "POST", body: form }),
      mocks.issue,
    ),

  getIssue: (id: string) =>
    mockOr<Issue | null>(() => request(`/issues/${id}`), mocks.issue),

  fixIssue: (id: string) =>
    mockOr<{ job_id: string }>(
      () => request(`/issues/${id}/fix`, { method: "POST" }),
      mocks.improve,
    ),

  listFixes: (agentId: string) =>
    mockOr<FixCard[]>(() => request(`/agents/${agentId}/fixes`), mocks.fixes),

  /** text/plain unified diff. */
  getFixDiff: async (agentId: string, toVersion: number) => {
    if (USE_MOCKS) return mocks.diff();
    const response = await fetch(
      `${API_URL}/agents/${agentId}/fixes/${toVersion}/diff`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      throw new ApiError(
        response.status,
        response.statusText,
        `/agents/${agentId}/fixes/${toVersion}/diff`,
      );
    }
    return response.text();
  },

  getInsights: (agentId: string) =>
    mockOr<Insights>(() => request(`/insights/${agentId}`), mocks.insights),

  getCompareInsights: () =>
    mockOr<CompareInsights>(
      () => request("/insights/compare"),
      mocks.compareInsights,
    ),

  /** §0.3 — the same case at v0 vs the current version. */
  compareCase: (agentId: string, caseId: string) =>
    mockOr<Compare | null>(
      () => request(`/agents/${agentId}/compare${query({ case_id: caseId })}`),
      mocks.compare,
    ),

  listEvents: (params: {
    agent_id?: string;
    kind?: string;
    since?: string | number;
  }) =>
    mockOr<LedgerEvent[]>(
      () => request(`/events${query(params)}`),
      mocks.events,
    ),

  getPlaybook: () => mockOr<Lesson[]>(() => request("/playbook"), mocks.lessons),

  listEvaluators: () =>
    mockOr<Evaluator[]>(() => request("/evaluators"), mocks.evaluators),
};

// ---------------------------------------------------------------------------
// Mock layer
// ---------------------------------------------------------------------------

async function mockOr<T>(live: () => Promise<T>, mock: () => T): Promise<T> {
  if (USE_MOCKS) return mock();
  return live();
}

/**
 * Phase 0 mocks: honest empty states, never invented numbers. W5 may add
 * realistic fixtures here for building the pages, clearly marked as mock data.
 */
export const mocks = {
  agents: (): Agent[] => [],
  agent: (): Agent | null => null,
  agentVersion: (): AgentVersion | null => null,
  createAgent: () => ({ agent_id: "mock", version: 0 }),
  run: () => ({ run_id: "mock" }),
  improve: () => ({ job_id: "mock" }),
  job: (): Job | null => null,
  issues: (): Issue[] => [],
  issue: (): Issue | null => null,
  fixes: (): FixCard[] => [],
  diff: () => "",
  events: (): LedgerEvent[] => [],
  lessons: (): Lesson[] => [],
  evaluators: (): Evaluator[] => [],
  compare: (): Compare | null => null,
  compareInsights: (): CompareInsights => ({ domains: [], ablation: null }),
  insights: (): Insights => ({
    pass_rate_by_version: [],
    cost_by_version: [],
    latency_by_version: [],
    fixes_by_lever: {},
    regressions_caught: 0,
    issues: { open: 0, closed: 0 },
    lessons_count: 0,
    drift: { count_by_kind: {}, tokens_saved: 0, cases_recovered_by_nudge: 0 },
    markers: [],
    memory_growth: [],
    tool_efficiency: [],
  }),
};
