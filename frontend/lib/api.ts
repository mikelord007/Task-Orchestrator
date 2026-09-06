/**
 * The only place the frontend talks to the backend.
 *
 * One exported function per endpoint in PLAN.md 4.5 (plus the 0.2-0.4
 * additions). Set NEXT_PUBLIC_USE_MOCKS=1 and every call is served from
 * lib/mocks instead, with identical types, so the whole UI is demoable before
 * the backend exists.
 */

import * as mocks from "./mocks";
import type {
  AgentDetail,
  AgentSummary,
  CompareResult,
  CreateAgentRequest,
  CreateAgentResponse,
  CreateIssueRequest,
  Evaluator,
  EventQuery,
  FixCard,
  ImproveRequest,
  Insights,
  InsightsCompare,
  Issue,
  Job,
  JobResponse,
  LedgerEvent,
  Lesson,
  MemoryEntryChange,
  RunRequest,
  RunResponse,
  RunSummary,
  Split,
} from "./types";

export * from "./types";

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

async function request<T>(
  path: string,
  init?: RequestInit & { text?: boolean },
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, path, detail || `${res.status} ${res.statusText}`);
  }
  if (init?.text) return (await res.text()) as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });

/* ------------------------------------------------------------------ agents */

/** POST /agents */
export async function createAgent(body: CreateAgentRequest): Promise<CreateAgentResponse> {
  if (USE_MOCKS) return mocks.createAgent(body);
  return request<CreateAgentResponse>("/agents", json(body));
}

/** GET /agents */
export async function listAgents(): Promise<AgentSummary[]> {
  if (USE_MOCKS) return mocks.listAgents();
  return request<AgentSummary[]>("/agents");
}

/** GET /agents/{id} */
export async function getAgent(agentId: string): Promise<AgentDetail> {
  if (USE_MOCKS) return mocks.getAgent(agentId);
  return request<AgentDetail>(`/agents/${encodeURIComponent(agentId)}`);
}

/** GET /agents/{id}/versions/{n} */
export async function getAgentVersion(agentId: string, version: number): Promise<AgentDetail> {
  if (USE_MOCKS) return mocks.getAgentVersion(agentId, version);
  return request<AgentDetail>(`/agents/${encodeURIComponent(agentId)}/versions/${version}`);
}

/** POST /agents/{id}/run */
export async function runAgent(agentId: string, body: RunRequest): Promise<RunResponse> {
  if (USE_MOCKS) return mocks.runAgent(agentId, body);
  return request<RunResponse>(`/agents/${encodeURIComponent(agentId)}/run`, json(body));
}

/** POST /agents/{id}/improve */
export async function improveAgent(agentId: string, body: ImproveRequest): Promise<JobResponse> {
  if (USE_MOCKS) return mocks.improveAgent(agentId, body);
  return request<JobResponse>(`/agents/${encodeURIComponent(agentId)}/improve`, json(body));
}

/** GET /agents/{id}/runs */
export async function listRuns(agentId: string): Promise<RunSummary[]> {
  if (USE_MOCKS) return mocks.listRuns(agentId);
  return request<RunSummary[]>(`/agents/${encodeURIComponent(agentId)}/runs`);
}

/** GET /agents/{id}/compare?case_id= */
export async function compareCase(agentId: string, caseId: string): Promise<CompareResult> {
  if (USE_MOCKS) return mocks.compareCase(agentId, caseId);
  return request<CompareResult>(
    `/agents/${encodeURIComponent(agentId)}/compare${qs({ case_id: caseId })}`,
  );
}

/**
 * Wire shape of one `memory_entries` item from `backend/ledger/metrics.py
 * fix_cards`: `entry_id` (not `id`) and no `change` field — a rule's
 * `demoted` flag stands in for it. `normalizeMemoryEntry` below maps this
 * onto `MemoryEntryChange` so components only ever see `id`/`change`.
 */
type RawMemoryEntry = Omit<MemoryEntryChange, "id" | "change"> & { entry_id: string };

function normalizeMemoryEntry(raw: RawMemoryEntry): MemoryEntryChange {
  const { entry_id, ...rest } = raw;
  return { ...rest, id: entry_id, change: raw.demoted ? "demoted" : "added" };
}

/** GET /agents/{id}/fixes */
export async function listFixes(agentId: string): Promise<FixCard[]> {
  if (USE_MOCKS) return mocks.listFixes(agentId);
  const raw = await request<(Omit<FixCard, "memory_entries"> & {
    memory_entries?: RawMemoryEntry[];
  })[]>(`/agents/${encodeURIComponent(agentId)}/fixes`);
  return raw.map((card) => ({
    ...card,
    memory_entries: card.memory_entries?.map(normalizeMemoryEntry),
  }));
}

/** GET /agents/{id}/fixes/{to_version}/diff -> text/plain unified diff */
export async function getFixDiff(agentId: string, toVersion: number): Promise<string> {
  if (USE_MOCKS) return mocks.getFixDiff(agentId, toVersion);
  return request<string>(
    `/agents/${encodeURIComponent(agentId)}/fixes/${toVersion}/diff`,
    { text: true },
  );
}

/* -------------------------------------------------------------------- jobs */

/** GET /jobs/{job_id} */
export async function getJob(jobId: string): Promise<Job> {
  if (USE_MOCKS) return mocks.getJob(jobId);
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

/* ------------------------------------------------------------------ issues */

/** GET /issues?agent_id= */
export async function listIssues(agentId?: string): Promise<Issue[]> {
  if (USE_MOCKS) return mocks.listIssues(agentId);
  return request<Issue[]>(`/issues${qs({ agent_id: agentId })}`);
}

/** POST /issues */
export async function createIssue(body: CreateIssueRequest): Promise<Issue> {
  if (USE_MOCKS) return mocks.createIssue(body);
  return request<Issue>("/issues", json(body));
}

/** GET /issues/{id} */
export async function getIssue(issueId: string): Promise<Issue> {
  if (USE_MOCKS) return mocks.getIssue(issueId);
  return request<Issue>(`/issues/${encodeURIComponent(issueId)}`);
}

/** POST /issues/{id}/fix */
export async function fixIssue(issueId: string): Promise<JobResponse> {
  if (USE_MOCKS) return mocks.fixIssue(issueId);
  return request<JobResponse>(`/issues/${encodeURIComponent(issueId)}/fix`, { method: "POST" });
}

/* ---------------------------------------------------------------- insights */

/** GET /insights/{agent_id} */
export async function getInsights(agentId: string): Promise<Insights> {
  if (USE_MOCKS) return mocks.getInsights(agentId);
  return request<Insights>(`/insights/${encodeURIComponent(agentId)}`);
}

/**
 * Wire shape of `GET /insights/compare` (`backend/ledger/metrics.py
 * insights_compare`): grouped by domain name, not a flat array, and each row
 * carries `goal` rather than a display `name`.
 */
interface RawInsightsCompare {
  by_domain: Record<
    string,
    {
      agent_id: string;
      goal?: string | null;
      domain: string;
      pass_at_1_by_version: InsightsCompare["domains"][number]["pass_at_1_by_version"];
    }[]
  >;
  ablation: InsightsCompare["ablation"];
}

/** GET /insights/compare */
export async function getInsightsCompare(): Promise<InsightsCompare> {
  if (USE_MOCKS) return mocks.getInsightsCompare();
  const raw = await request<RawInsightsCompare>("/insights/compare");
  return {
    domains: Object.values(raw.by_domain)
      .flat()
      .map((d) => ({
        agent_id: d.agent_id,
        name: d.goal || d.agent_id,
        domain: d.domain,
        pass_at_1_by_version: d.pass_at_1_by_version,
      })),
    ablation: raw.ablation,
  };
}

/* ---------------------------------------------------- playbook and events */

/** GET /playbook */
export async function getPlaybook(): Promise<Lesson[]> {
  if (USE_MOCKS) return mocks.getPlaybook();
  return request<Lesson[]>("/playbook");
}

/** GET /evaluators */
export async function listEvaluators(): Promise<Evaluator[]> {
  if (USE_MOCKS) return mocks.listEvaluators();
  return request<Evaluator[]>("/evaluators");
}

/** GET /events?agent_id=&kind=&since= */
export async function listEvents(query: EventQuery = {}): Promise<LedgerEvent[]> {
  if (USE_MOCKS) return mocks.listEvents(query);
  return request<LedgerEvent[]>(`/events${qs({ ...query })}`);
}

/* ----------------------------------------------------------------- helpers */

/** Latest run per (version, split), newest first, for the runs tab filters. */
export function filterRuns(runs: RunSummary[], split?: Split, version?: number): RunSummary[] {
  return runs.filter(
    (r) => (split ? r.split === split : true) && (version === undefined ? true : r.version === version),
  );
}
