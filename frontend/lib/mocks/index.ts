/**
 * Mock implementations of every api.ts call, active when
 * NEXT_PUBLIC_USE_MOCKS=1. Same types as the real client.
 *
 * Jobs advance on wall-clock time so the polling hook and the progress bar are
 * exercised for real rather than faked in the component.
 */

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
  RunRequest,
  RunResponse,
  RunSummary,
} from "../types";
import * as data from "./data";

const LATENCY_MS = 120;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/* ------------------------------------------------------- in-memory writes */

const createdAgents: AgentSummary[] = [];
const createdIssues: Issue[] = [];

/* -------------------------------------------------------------- fake jobs */

interface FakeJob {
  job_id: string;
  kind: string;
  total: number;
  startedAt: number;
  durationMs: number;
}

const jobs = new Map<string, FakeJob>();
let jobSeq = 0;

function startJob(kind: string, total: number, durationMs: number): JobResponse {
  const job_id = `job-${++jobSeq}-${kind}`;
  jobs.set(job_id, { job_id, kind, total, startedAt: Date.now(), durationMs });
  return { job_id };
}

export async function getJob(jobId: string): Promise<Job> {
  const job = jobs.get(jobId);
  if (!job) {
    return delay<Job>({
      job_id: jobId,
      kind: "unknown",
      status: "error",
      progress: { done: 0, total: 0 },
      error: "No such job. Mock jobs live only for the lifetime of the tab.",
    });
  }
  const elapsed = Date.now() - job.startedAt;
  const fraction = Math.min(1, elapsed / job.durationMs);
  const done = Math.floor(fraction * job.total);
  const status: Job["status"] = fraction >= 1 ? "done" : elapsed < 400 ? "queued" : "running";
  return delay<Job>({
    job_id: job.job_id,
    kind: job.kind,
    status,
    progress: { done: status === "done" ? job.total : done, total: job.total },
    result:
      status === "done"
        ? job.kind === "improve"
          ? { accepted: 1, rejected: 1, to_version: 3 }
          : { run_id: "run-a-t3" }
        : undefined,
  });
}

/* ------------------------------------------------------------------ agents */

export async function listAgents(): Promise<AgentSummary[]> {
  return delay(clone([...createdAgents, ...data.AGENTS]));
}

export async function getAgent(agentId: string): Promise<AgentDetail> {
  return delay(clone(data.agentDetail(agentId)));
}

export async function getAgentVersion(agentId: string, version: number): Promise<AgentDetail> {
  return delay(clone(data.agentDetail(agentId, version)));
}

export async function createAgent(body: CreateAgentRequest): Promise<CreateAgentResponse> {
  const agent_id = `agent-${createdAgents.length + 1}-${body.domain}`;
  createdAgents.unshift({
    agent_id,
    name: body.domain.replace(/_/g, "-"),
    goal: body.goal,
    domain: body.domain,
    evaluator_id: body.evaluator_id,
    current_version: 0,
    created_ts: new Date().toISOString(),
    latest_train: null,
    latest_holdout: null,
  });
  return delay({ agent_id, version: 0 });
}

export async function runAgent(agentId: string, body: RunRequest): Promise<RunResponse> {
  const job = startJob(`run:${body.split}`, 12, 6000);
  return delay({ run_id: job.job_id });
}

export async function improveAgent(
  agentId: string,
  body: ImproveRequest,
): Promise<JobResponse> {
  return delay(startJob("improve", Math.max(1, body.max_attempts), 9000));
}

export async function listRuns(agentId: string): Promise<RunSummary[]> {
  return delay(clone(data.RUNS[agentId] ?? []));
}

export async function compareCase(agentId: string, caseId: string): Promise<CompareResult> {
  return delay(clone(data.compareFor(agentId, caseId)));
}

export async function listFixes(agentId: string): Promise<FixCard[]> {
  return delay(clone(data.FIXES[agentId] ?? []));
}

export async function getFixDiff(agentId: string, toVersion: number): Promise<string> {
  return delay(
    data.DIFFS[`${agentId}:${toVersion}`] ??
      "No diff on disk for this version. Memory fixes carry their entries on the card instead.",
  );
}

/* ------------------------------------------------------------------ issues */

export async function listIssues(agentId?: string): Promise<Issue[]> {
  const all = [...createdIssues, ...data.ISSUES];
  return delay(clone(agentId ? all.filter((i) => i.agent_id === agentId) : all));
}

export async function getIssue(issueId: string): Promise<Issue> {
  const found = [...createdIssues, ...data.ISSUES].find((i) => i.issue_id === issueId);
  if (!found) throw new Error(`No issue ${issueId}`);
  return delay(clone(found));
}

export async function createIssue(body: CreateIssueRequest): Promise<Issue> {
  const issue: Issue = {
    issue_id: `iss-${100 + createdIssues.length}`,
    agent_id: body.agent_id,
    title: body.title,
    body: body.body,
    source: "human",
    status: "open",
    created_ts: new Date().toISOString(),
    linked_case_ids: [],
  };
  createdIssues.unshift(issue);
  return delay(clone(issue));
}

export async function fixIssue(issueId: string): Promise<JobResponse> {
  return delay(startJob("improve", 3, 9000));
}

/* ---------------------------------------------------------------- insights */

export async function getInsights(agentId: string): Promise<Insights> {
  const found = data.INSIGHTS[agentId];
  if (found) return delay(clone(found));
  return delay<Insights>({
    agent_id: agentId,
    trials: data.TRIALS,
    pass_at_1_by_version: [],
    pass_pow_k_by_version: [],
    cost_by_version: [],
    latency_by_version: [],
    fixes_by_lever: {},
    regressions_caught: 0,
    issues: { open: 0, closed: 0 },
    lessons_count: 0,
    drift: { count_by_kind: {}, tokens_saved: 0, cases_recovered_by_nudge: 0 },
    markers: [],
    memory_by_version: [],
    tool_stats_by_version: [],
    graduated_count: 0,
    saturated: false,
    flagged_tasks: [],
  });
}

export async function getInsightsCompare(): Promise<InsightsCompare> {
  return delay(clone(data.COMPARE_DOMAINS));
}

/* ---------------------------------------------------- playbook and events */

export async function getPlaybook(): Promise<Lesson[]> {
  return delay(clone(data.PLAYBOOK));
}

export async function listEvaluators(): Promise<Evaluator[]> {
  return delay(clone(data.EVALUATORS));
}

export async function listEvents(query: EventQuery = {}): Promise<LedgerEvent[]> {
  let events = clone(data.EVENTS);
  if (query.agent_id) events = events.filter((e) => e.agent_id === query.agent_id);
  if (query.kind) events = events.filter((e) => e.kind === query.kind);
  if (query.since) events = events.filter((e) => e.ts >= query.since!);
  return delay(events);
}
