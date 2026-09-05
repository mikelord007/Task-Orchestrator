/**
 * Demo fixtures. One GitHub-triage agent improved across three accepted
 * versions with one rejected candidate and one demoted rule, plus a second
 * agent in a different domain so the cross-domain panels have something to
 * compare. Run statistics are derived from the per-repeat pass matrices in
 * derive.ts, never typed by hand.
 */

import type {
  AgentDetail,
  AgentSummary,
  CompareResult,
  Evaluator,
  FixCard,
  Insights,
  InsightsCompare,
  Issue,
  LedgerEvent,
  Lesson,
  MemoryEntryChange,
  MemoryRule,
  RunSummary,
  ToolNote,
} from "../types";
import { makeRun, row } from "./derive";

export const AGENT_A = "gh-triage-01";
export const AGENT_B = "ticket-triage-01";
export const REPEATS = 3;

/* ------------------------------------------------------------- evaluators */

export const EVALUATORS: Evaluator[] = [
  {
    evaluator_id: "github_triage",
    domain: "github_triage",
    description:
      "Given an open issue from Untrivial-ai/agent-orchestrator, produce labels, component, assignee, duplicate_of and priority. Ground truth is what the maintainers actually applied. Split is temporal: train is the oldest 70% of closed issues, holdout the newest 30%.",
    allowed_tools: [
      "list_issues",
      "get_issue",
      "list_issue_comments",
      "list_labels",
      "search_issues",
      "get_file",
      "list_recent_commits",
    ],
    case_counts: { train: 42, holdout: 18 },
  },
  {
    evaluator_id: "ticket_triage",
    domain: "ticket_triage",
    description:
      "Given a support ticket, produce category, priority and needs_human. Hard cases are tagged: mixed language, sarcasm, several problems in one ticket, a p0 signal buried in the last line.",
    allowed_tools: ["html_to_text", "regex_extract", "date_parse", "json_validate", "number_parse"],
    case_counts: { train: 35, holdout: 15 },
  },
];

/* ----------------------------------------------------------------- memory */

const RULES_V3: MemoryRule[] = [
  {
    id: "r-001",
    rule: "An issue that mentions ConPTY, winpty, or a PowerShell prompt that renders wrong gets platform:windows alongside bug. The maintainers have applied it to every such report.",
    scope_keywords: ["conpty", "winpty", "powershell", "windows", "terminal", "render"],
    evidence_case_ids: ["gh-1731", "gh-1802", "gh-1877"],
    confidence: 0.86,
    hits: 9,
    misses: 1,
    created_version: 1,
    source: "reflection",
  },
  {
    id: "r-002",
    rule: "Map the file path in the report to the component: src/session/ is session, src/ui/ is tui, src/provider/ is providers, scripts/ is tooling. CODEOWNERS lists the same four owners.",
    scope_keywords: ["path", "file", "src/", "traceback", "component", "codeowners"],
    evidence_case_ids: ["gh-1758", "gh-1846", "gh-2011"],
    confidence: 0.91,
    hits: 12,
    misses: 0,
    created_version: 1,
    source: "reflection",
  },
  {
    id: "r-003",
    rule: "A report that describes a capability the author wants, with no reproduction steps, is enhancement rather than bug even when the author writes that something is broken.",
    scope_keywords: ["would be nice", "feature", "support for", "broken", "cannot"],
    evidence_case_ids: ["gh-1903", "gh-1975"],
    confidence: 0.74,
    hits: 6,
    misses: 2,
    created_version: 1,
    source: "reflection",
  },
  {
    id: "r-004",
    rule: "An issue opened by a maintainer is priority p1.",
    scope_keywords: ["maintainer", "author", "team"],
    evidence_case_ids: ["gh-1846"],
    confidence: 0.31,
    hits: 1,
    misses: 5,
    created_version: 1,
    source: "reflection",
    demoted: true,
    demoted_version: 3,
  },
  {
    id: "r-005",
    rule: "Before answering duplicate_of, search closed issues as well. Maintainers close the duplicate and keep the original open, so the original is invisible with the default state filter.",
    scope_keywords: ["duplicate", "same as", "already reported", "search"],
    evidence_case_ids: ["gh-1948", "gh-2044", "gh-2103"],
    confidence: 0.8,
    hits: 4,
    misses: 0,
    created_version: 3,
    source: "reflection",
  },
  {
    id: "r-006",
    rule: "A crash report whose traceback contains agent_loop.py belongs to component runtime, not session, even though the session module appears higher in the stack.",
    scope_keywords: ["traceback", "crash", "agent_loop", "runtime", "session"],
    evidence_case_ids: ["gh-2204"],
    confidence: 0.79,
    hits: 3,
    misses: 0,
    created_version: 3,
    source: "issue",
  },
];

const TOOL_NOTES_V3: ToolNote[] = [
  {
    id: "t-001",
    tool: "list_issues",
    note: "Paginates at 100 and defaults to state=open. Pass state=all when hunting duplicates or the closed original never appears.",
    evidence: "12 of the 14 duplicate_of misses in v0 called list_issues with the default state.",
    created_version: 1,
  },
  {
    id: "t-002",
    tool: "list_labels",
    note: "Returns a description for every label. Read it rather than inferring from the name: area:tui is described as terminal rendering, which is wider than the name suggests.",
    evidence: "Label descriptions were fetched in 3 of 42 v0 cases and in all of them the label set was correct.",
    created_version: 1,
  },
  {
    id: "t-003",
    tool: "get_file",
    note: "Returns raw file contents and cannot list a directory. Read CODEOWNERS once and reuse it instead of calling get_file per candidate path.",
    evidence: "v1 averaged 4.1 get_file calls per case, v3 averages 1.0 for the same component accuracy.",
    created_version: 3,
  },
];

const MEMORY_V3 = {
  rules: RULES_V3,
  tool_notes: TOOL_NOTES_V3,
  episodes: [
    {
      id: "e-004",
      text: "v3 train: duplicate_of resolved on all three duplicate cases once closed issues were searched; r-004 injected 6 times for 1 hit and was demoted.",
      created_version: 3,
      run_id: "run-a-t3",
      ts: "2026-09-06T09:41:00Z",
    },
    {
      id: "e-003",
      text: "v2 train: the deepest-path instruction fixed the component group but broke two enhancement cases that cite a file only as an example.",
      created_version: 2,
      run_id: "run-a-t2",
      ts: "2026-09-06T08:12:00Z",
    },
    {
      id: "e-002",
      text: "v1 train: platform:windows now applied on all five Windows reports; component still wrong whenever the body names more than one file.",
      created_version: 1,
      run_id: "run-a-t1",
      ts: "2026-09-06T06:55:00Z",
    },
    {
      id: "e-001",
      text: "v0 train: 9.2 tool calls per case, most of them repeated list_issues searches that returned the same page.",
      created_version: 0,
      run_id: "run-a-t0",
      ts: "2026-09-06T05:30:00Z",
    },
  ],
};

const MEMORY_BY_VERSION: Record<number, AgentDetail["memory"]> = {
  0: { rules: [], tool_notes: [], episodes: MEMORY_V3.episodes.slice(3) },
  1: {
    rules: RULES_V3.filter((r) => r.created_version <= 1).map((r) => ({ ...r, demoted: false })),
    tool_notes: TOOL_NOTES_V3.filter((t) => t.created_version <= 1),
    episodes: MEMORY_V3.episodes.slice(2),
  },
  2: {
    rules: RULES_V3.filter((r) => r.created_version <= 1).map((r) => ({ ...r, demoted: false })),
    tool_notes: TOOL_NOTES_V3.filter((t) => t.created_version <= 1),
    episodes: MEMORY_V3.episodes.slice(1),
  },
  3: MEMORY_V3,
};

/* ----------------------------------------------------------------- agents */

const PROMPT_V3 = `# Role

You triage issues for Untrivial-ai/agent-orchestrator. For one open issue you
return exactly this object and nothing else:

    {"labels": [...], "component": "...", "assignee": "..."|null,
     "duplicate_of": <number>|null, "priority": "p0"|"p1"|"p2"|"p3"}

# Method

1. Read the issue body and every comment before calling any other tool.
2. Fetch the label list once. Use the description field, not the label name, to
   decide whether a label applies.
3. If the body names a file path or contains a traceback, map the path to a
   component. Read CODEOWNERS once; do not call get_file per candidate path.
4. Before answering duplicate_of, search with state=all. The original of a
   duplicate is usually already closed.
5. Priority comes from impact and from what the reporter is blocked on, never
   from who opened the issue.

# Output

Emit the object as the final message. Do not explain your reasoning, do not
restate the issue, and do not report on your own accuracy.`;

const PROMPT_V0 = `# Role

You triage issues for a GitHub repository. Given an issue, return the labels,
component, assignee, duplicate and priority you think the maintainers would
apply.

# Method

Use the tools available to you to gather whatever context you need, then answer
with a JSON object.`;

const TOOLS_A = [
  {
    name: "list_issues",
    description:
      "List issues in the repository, newest first. Returns number, title, state, labels, author and creation date for each. Paginates at 100; pass state=all to include closed issues. Does not return issue bodies or comments.",
  },
  {
    name: "get_issue",
    description:
      "Return one issue in full: title, body, author, state, labels, assignees and timestamps. Use it once you have a candidate number from list_issues or search_issues.",
  },
  {
    name: "list_issue_comments",
    description:
      "Return every comment on one issue in order, with author and timestamp. Maintainer conventions are usually stated here rather than in the body.",
  },
  {
    name: "list_labels",
    description:
      "Return every label in the repository with its colour and description. Use the description to decide whether a label applies. Does not tell you which labels are currently on an issue.",
  },
  {
    name: "search_issues",
    description:
      "Search issues by GitHub search syntax and return matching numbers and titles. Use it to look for an earlier report of the same problem. Ranking is GitHub's, so read more than the first result.",
  },
  {
    name: "get_file",
    description:
      "Return the raw contents of one file at the default branch. Use it for CODEOWNERS or a module docstring. It cannot list a directory and it does not search.",
  },
  {
    name: "list_recent_commits",
    description:
      "Return recent commits, optionally filtered to a path, with message, author and date. Use it to find who last touched the code a report points at.",
  },
];

const BASE_A: AgentSummary = {
  agent_id: AGENT_A,
  name: "github-triage",
  goal: "Triage an open issue in Untrivial-ai/agent-orchestrator the way its maintainers do: labels, component, assignee, duplicate and priority.",
  domain: "github_triage",
  evaluator_id: "github_triage",
  current_version: 3,
  created_ts: "2026-09-06T05:02:00Z",
  latest_train: null,
  latest_holdout: null,
};

const BASE_B: AgentSummary = {
  agent_id: AGENT_B,
  name: "ticket-triage",
  goal: "Route a support ticket: category, priority, and whether a human has to look at it.",
  domain: "ticket_triage",
  evaluator_id: "ticket_triage",
  current_version: 2,
  created_ts: "2026-09-06T10:15:00Z",
  latest_train: null,
  latest_holdout: null,
};

/* ------------------------------------------------------------------- runs */

const TRACE = (id: string) => `https://app.neatlogs.com/trace/${id}`;

const RUNS_A: RunSummary[] = [
  makeRun({
    run_id: "run-a-t0",
    version: 0,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T05:10:00Z",
    finished_ts: "2026-09-06T05:29:00Z",
    cases: [
      row("gh-1731", "...", { score: 0.34, cost_usd: 0.038, latency_ms: 13400, tool_calls: 11, tool_errors: 2, trace_url: TRACE("a0-1731") }),
      row("gh-1758", "xxx", { score: 0.96, cost_usd: 0.029, latency_ms: 9800, tool_calls: 7 }),
      row("gh-1802", "...", { score: 0.31, cost_usd: 0.041, latency_ms: 14100, tool_calls: 12, tool_errors: 3, trace_url: TRACE("a0-1802") }),
      row("gh-1846", "xx.", { score: 0.71, cost_usd: 0.033, latency_ms: 11200, tool_calls: 9 }),
      row("gh-1877", "...", { score: 0.4, cost_usd: 0.036, latency_ms: 12600, tool_calls: 10, tool_errors: 1 }),
      row("gh-1903", "xxx", { score: 0.93, cost_usd: 0.027, latency_ms: 8900, tool_calls: 6 }),
      row("gh-1948", "...", { score: 0.12, cost_usd: 0.052, latency_ms: 21800, tool_calls: 18, tool_errors: 4, drift_kind: "loop", trace_url: TRACE("a0-1948") }),
      row("gh-1975", ".x.", { score: 0.55, cost_usd: 0.031, latency_ms: 10400, tool_calls: 8 }),
      row("gh-2011", "xxx", { score: 0.95, cost_usd: 0.026, latency_ms: 8600, tool_calls: 6 }),
      row("gh-2044", "...", { score: 0.29, cost_usd: 0.043, latency_ms: 15300, tool_calls: 13, tool_errors: 2 }),
      row("gh-2077", "x.x", { score: 0.68, cost_usd: 0.032, latency_ms: 10900, tool_calls: 8 }),
      row("gh-2103", "...", { score: 0.33, cost_usd: 0.044, latency_ms: 16200, tool_calls: 12, tool_errors: 2, drift_kind: "budget" }),
    ],
  }),
  makeRun({
    run_id: "run-a-h0",
    version: 0,
    split: "holdout",
    repeats: REPEATS,
    started_ts: "2026-09-06T05:31:00Z",
    finished_ts: "2026-09-06T05:40:00Z",
    cases: [
      row("gh-2141", "...", { score: 0.3, cost_usd: 0.04, latency_ms: 13900, tool_calls: 11, tool_errors: 1 }),
      row("gh-2166", "xxx", { score: 0.94, cost_usd: 0.028, latency_ms: 9100, tool_calls: 7 }),
      row("gh-2189", "...", { score: 0.26, cost_usd: 0.045, latency_ms: 15600, tool_calls: 13, tool_errors: 2 }),
      row("gh-2204", ".x.", { score: 0.52, cost_usd: 0.037, latency_ms: 12800, tool_calls: 10 }),
      row("gh-2231", "...", { score: 0.35, cost_usd: 0.039, latency_ms: 13100, tool_calls: 10, tool_errors: 1 }),
      row("gh-2258", "xx.", { score: 0.74, cost_usd: 0.03, latency_ms: 9900, tool_calls: 7 }),
    ],
  }),
  makeRun({
    run_id: "run-a-t1",
    version: 1,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T06:41:00Z",
    finished_ts: "2026-09-06T06:57:00Z",
    cases: [
      row("gh-1731", "xxx", { score: 0.92, cost_usd: 0.03, latency_ms: 10100, tool_calls: 7, rules_injected: ["r-001", "r-002"] }),
      row("gh-1758", "xxx", { score: 0.97, cost_usd: 0.026, latency_ms: 8700, tool_calls: 6, rules_injected: ["r-002"] }),
      row("gh-1802", "xx.", { score: 0.78, cost_usd: 0.031, latency_ms: 10600, tool_calls: 7, rules_injected: ["r-001", "r-002"] }),
      row("gh-1846", "xxx", { score: 0.9, cost_usd: 0.028, latency_ms: 9400, tool_calls: 6, rules_injected: ["r-002", "r-004"] }),
      row("gh-1877", "...", { score: 0.42, cost_usd: 0.035, latency_ms: 12000, tool_calls: 9, tool_errors: 1, rules_injected: ["r-001", "r-003"] }),
      row("gh-1903", "xxx", { score: 0.94, cost_usd: 0.025, latency_ms: 8300, tool_calls: 5, rules_injected: ["r-003"] }),
      row("gh-1948", ".x.", { score: 0.48, cost_usd: 0.04, latency_ms: 14200, tool_calls: 11, tool_errors: 2, rules_injected: ["r-002"], trace_url: TRACE("a1-1948") }),
      row("gh-1975", "xxx", { score: 0.89, cost_usd: 0.027, latency_ms: 8800, tool_calls: 6, rules_injected: ["r-003"] }),
      row("gh-2011", "xxx", { score: 0.96, cost_usd: 0.025, latency_ms: 8200, tool_calls: 5, rules_injected: ["r-002"] }),
      row("gh-2044", "...", { score: 0.31, cost_usd: 0.038, latency_ms: 13400, tool_calls: 10, tool_errors: 1, rules_injected: ["r-001", "r-004"] }),
      row("gh-2077", "xxx", { score: 0.91, cost_usd: 0.027, latency_ms: 8900, tool_calls: 6, rules_injected: ["r-002"] }),
      row("gh-2103", ".x.", { score: 0.5, cost_usd: 0.037, latency_ms: 12700, tool_calls: 9, tool_errors: 1, rules_injected: ["r-001", "r-004"] }),
    ],
  }),
  makeRun({
    run_id: "run-a-h1",
    version: 1,
    split: "holdout",
    repeats: REPEATS,
    started_ts: "2026-09-06T06:58:00Z",
    finished_ts: "2026-09-06T07:06:00Z",
    cases: [
      row("gh-2141", "xxx", { score: 0.9, cost_usd: 0.029, latency_ms: 9600, tool_calls: 7, rules_injected: ["r-001"] }),
      row("gh-2166", "xxx", { score: 0.95, cost_usd: 0.026, latency_ms: 8500, tool_calls: 6, rules_injected: ["r-002"] }),
      row("gh-2189", "...", { score: 0.28, cost_usd: 0.039, latency_ms: 13800, tool_calls: 11, tool_errors: 2, rules_injected: ["r-004"] }),
      row("gh-2204", ".x.", { score: 0.51, cost_usd: 0.034, latency_ms: 11700, tool_calls: 9, rules_injected: ["r-002"] }),
      row("gh-2231", "xx.", { score: 0.72, cost_usd: 0.03, latency_ms: 9900, tool_calls: 7, rules_injected: ["r-001", "r-003"] }),
      row("gh-2258", "xxx", { score: 0.93, cost_usd: 0.027, latency_ms: 8800, tool_calls: 6, rules_injected: ["r-003"] }),
    ],
  }),
  // Gate run for the rejected candidate: train only, no holdout was ever run.
  makeRun({
    run_id: "run-a-t2",
    version: 2,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T07:58:00Z",
    finished_ts: "2026-09-06T08:11:00Z",
    cases: [
      row("gh-1731", "xxx", { score: 0.92, cost_usd: 0.03, latency_ms: 10000, tool_calls: 7, rules_injected: ["r-001", "r-002"] }),
      row("gh-1758", ".x.", { score: 0.49, cost_usd: 0.031, latency_ms: 10300, tool_calls: 7, rules_injected: ["r-002"] }),
      row("gh-1802", "xxx", { score: 0.88, cost_usd: 0.03, latency_ms: 10100, tool_calls: 7, rules_injected: ["r-001", "r-002"] }),
      row("gh-1846", "xxx", { score: 0.9, cost_usd: 0.028, latency_ms: 9500, tool_calls: 6, rules_injected: ["r-002", "r-004"] }),
      row("gh-1877", "x.x", { score: 0.68, cost_usd: 0.033, latency_ms: 11400, tool_calls: 8, rules_injected: ["r-001", "r-003"] }),
      row("gh-1903", "xxx", { score: 0.94, cost_usd: 0.026, latency_ms: 8600, tool_calls: 6, rules_injected: ["r-003"] }),
      row("gh-1948", "...", { score: 0.3, cost_usd: 0.041, latency_ms: 14600, tool_calls: 11, tool_errors: 2, rules_injected: ["r-002"] }),
      row("gh-1975", "xxx", { score: 0.87, cost_usd: 0.028, latency_ms: 9100, tool_calls: 6, rules_injected: ["r-003"] }),
      row("gh-2011", "...", { score: 0.41, cost_usd: 0.032, latency_ms: 10800, tool_calls: 7, rules_injected: ["r-002"] }),
      row("gh-2044", "...", { score: 0.33, cost_usd: 0.039, latency_ms: 13600, tool_calls: 10, tool_errors: 1, rules_injected: ["r-001", "r-004"] }),
      row("gh-2077", "xxx", { score: 0.9, cost_usd: 0.028, latency_ms: 9200, tool_calls: 6, rules_injected: ["r-002"] }),
      row("gh-2103", "...", { score: 0.36, cost_usd: 0.038, latency_ms: 13100, tool_calls: 10, tool_errors: 1, rules_injected: ["r-001", "r-004"] }),
    ],
  }),
  makeRun({
    run_id: "run-a-t3",
    version: 3,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T09:22:00Z",
    finished_ts: "2026-09-06T09:34:00Z",
    cases: [
      row("gh-1731", "xxx", { score: 0.97, cost_usd: 0.021, latency_ms: 7100, tool_calls: 4, rules_injected: ["r-001", "r-002"] }),
      row("gh-1758", "xxx", { score: 0.98, cost_usd: 0.019, latency_ms: 6600, tool_calls: 4, rules_injected: ["r-002"] }),
      row("gh-1802", "xxx", { score: 0.95, cost_usd: 0.02, latency_ms: 6900, tool_calls: 4, rules_injected: ["r-001", "r-002"] }),
      row("gh-1846", "xxx", { score: 0.93, cost_usd: 0.021, latency_ms: 7200, tool_calls: 4, rules_injected: ["r-002"] }),
      row("gh-1877", "xx.", { score: 0.76, cost_usd: 0.023, latency_ms: 7900, tool_calls: 5, rules_injected: ["r-001", "r-003"] }),
      row("gh-1903", "xxx", { score: 0.96, cost_usd: 0.018, latency_ms: 6300, tool_calls: 3, rules_injected: ["r-003"] }),
      row("gh-1948", "xxx", { score: 0.91, cost_usd: 0.023, latency_ms: 8000, tool_calls: 5, rules_injected: ["r-002", "r-005"], trace_url: TRACE("a3-1948") }),
      row("gh-1975", "xxx", { score: 0.94, cost_usd: 0.019, latency_ms: 6700, tool_calls: 4, rules_injected: ["r-003"] }),
      row("gh-2011", "xxx", { score: 0.97, cost_usd: 0.018, latency_ms: 6200, tool_calls: 3, rules_injected: ["r-002"] }),
      row("gh-2044", ".x.", { score: 0.54, cost_usd: 0.026, latency_ms: 9100, tool_calls: 6, tool_errors: 1, rules_injected: ["r-001", "r-005"] }),
      row("gh-2077", "xxx", { score: 0.95, cost_usd: 0.019, latency_ms: 6500, tool_calls: 4, rules_injected: ["r-002"] }),
      row("gh-2103", "x.x", { score: 0.79, cost_usd: 0.024, latency_ms: 8300, tool_calls: 5, rules_injected: ["r-001", "r-005"] }),
    ],
  }),
  makeRun({
    run_id: "run-a-h3",
    version: 3,
    split: "holdout",
    repeats: REPEATS,
    started_ts: "2026-09-06T09:35:00Z",
    finished_ts: "2026-09-06T09:42:00Z",
    cases: [
      row("gh-2141", "xxx", { score: 0.94, cost_usd: 0.02, latency_ms: 6800, tool_calls: 4, rules_injected: ["r-001"] }),
      row("gh-2166", "xxx", { score: 0.96, cost_usd: 0.019, latency_ms: 6400, tool_calls: 4, rules_injected: ["r-002"] }),
      row("gh-2189", ".x.", { score: 0.5, cost_usd: 0.027, latency_ms: 9400, tool_calls: 6, tool_errors: 1, rules_injected: ["r-003"] }),
      row("gh-2204", "xxx", { score: 0.92, cost_usd: 0.021, latency_ms: 7000, tool_calls: 4, rules_injected: ["r-002", "r-006"] }),
      row("gh-2231", "xx.", { score: 0.77, cost_usd: 0.023, latency_ms: 7800, tool_calls: 5, rules_injected: ["r-001", "r-003"] }),
      row("gh-2258", "xxx", { score: 0.95, cost_usd: 0.019, latency_ms: 6600, tool_calls: 4, rules_injected: ["r-003"] }),
    ],
  }),
];

const RUNS_B: RunSummary[] = [
  makeRun({
    run_id: "run-b-t0",
    version: 0,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T10:20:00Z",
    finished_ts: "2026-09-06T10:27:00Z",
    cases: [
      row("tk-014", "x..", { score: 0.51, cost_usd: 0.008, latency_ms: 3100, tool_calls: 2 }),
      row("tk-021", "xxx", { score: 0.92, cost_usd: 0.007, latency_ms: 2700, tool_calls: 2 }),
      row("tk-033", "...", { score: 0.22, cost_usd: 0.009, latency_ms: 3600, tool_calls: 3, tool_errors: 1 }),
      row("tk-041", "xx.", { score: 0.7, cost_usd: 0.008, latency_ms: 3000, tool_calls: 2 }),
      row("tk-047", "...", { score: 0.3, cost_usd: 0.009, latency_ms: 3400, tool_calls: 3 }),
      row("tk-052", "xxx", { score: 0.9, cost_usd: 0.007, latency_ms: 2600, tool_calls: 2 }),
    ],
  }),
  makeRun({
    run_id: "run-b-t2",
    version: 2,
    split: "train",
    repeats: REPEATS,
    started_ts: "2026-09-06T11:44:00Z",
    finished_ts: "2026-09-06T11:50:00Z",
    cases: [
      row("tk-014", "xxx", { score: 0.9, cost_usd: 0.006, latency_ms: 2400, tool_calls: 2, rules_injected: ["rb-002"] }),
      row("tk-021", "xxx", { score: 0.94, cost_usd: 0.006, latency_ms: 2300, tool_calls: 2 }),
      row("tk-033", "xx.", { score: 0.71, cost_usd: 0.007, latency_ms: 2800, tool_calls: 2, rules_injected: ["rb-001"] }),
      row("tk-041", "xxx", { score: 0.89, cost_usd: 0.006, latency_ms: 2500, tool_calls: 2 }),
      row("tk-047", "x.x", { score: 0.68, cost_usd: 0.007, latency_ms: 2700, tool_calls: 2, rules_injected: ["rb-001"] }),
      row("tk-052", "xxx", { score: 0.93, cost_usd: 0.006, latency_ms: 2300, tool_calls: 2 }),
    ],
  }),
  makeRun({
    run_id: "run-b-h2",
    version: 2,
    split: "holdout",
    repeats: REPEATS,
    started_ts: "2026-09-06T11:51:00Z",
    finished_ts: "2026-09-06T11:55:00Z",
    cases: [
      row("tk-061", "xxx", { score: 0.91, cost_usd: 0.006, latency_ms: 2400, tool_calls: 2 }),
      row("tk-068", "xx.", { score: 0.73, cost_usd: 0.007, latency_ms: 2600, tool_calls: 2, rules_injected: ["rb-001"] }),
      row("tk-074", "xxx", { score: 0.9, cost_usd: 0.006, latency_ms: 2300, tool_calls: 2 }),
      row("tk-079", "...", { score: 0.28, cost_usd: 0.008, latency_ms: 3000, tool_calls: 3, tool_errors: 1 }),
    ],
  }),
];

export const RUNS: Record<string, RunSummary[]> = { [AGENT_A]: RUNS_A, [AGENT_B]: RUNS_B };

function latest(agentId: string, split: "train" | "holdout", version: number) {
  const found = RUNS[agentId]
    .filter((r) => r.split === split && r.version === version)
    .slice(-1)[0];
  return found ? found.pass_rate : null;
}

export const AGENTS: AgentSummary[] = [
  { ...BASE_A, latest_train: latest(AGENT_A, "train", 3), latest_holdout: latest(AGENT_A, "holdout", 3) },
  { ...BASE_B, latest_train: latest(AGENT_B, "train", 2), latest_holdout: latest(AGENT_B, "holdout", 2) },
];

/* ---------------------------------------------------------- agent details */

export function agentDetail(agentId: string, version?: number): AgentDetail {
  if (agentId === AGENT_B) {
    const v = version ?? BASE_B.current_version;
    return {
      ...AGENTS[1],
      version: v,
      model_strong: "claude-opus-5",
      model_cheap: "claude-haiku-4-5-20251001",
      orchestration: "single",
      routing: { extract: "cheap", classify: "cheap" },
      prompt:
        "# Role\n\nYou route one support ticket. Return {category, priority, needs_human}.\n\n# Method\n\nRead the whole ticket before deciding. The strongest signal is often in the\nlast sentence. Sarcasm is not priority; a stated deadline is.",
      tools: [
        { name: "html_to_text", description: "Strip markup from a ticket body and return plain text with the paragraph breaks kept." },
        { name: "date_parse", description: "Parse a date or a relative expression such as 'by Friday' into an ISO date, given a reference timestamp." },
      ],
      memory: {
        rules: [
          {
            id: "rb-001",
            rule: "A ticket that names a deadline in the last sentence is at least p1 regardless of how calm the rest of it reads.",
            scope_keywords: ["deadline", "by friday", "before", "eod"],
            evidence_case_ids: ["tk-033", "tk-047"],
            confidence: 0.83,
            hits: 5,
            misses: 1,
            created_version: 1,
            source: "reflection",
          },
          {
            id: "rb-002",
            rule: "Sarcasm markers raise tone, not priority. Grade on what the customer cannot do, not on how they say it.",
            scope_keywords: ["great", "wonderful", "love that", "again"],
            evidence_case_ids: ["tk-014"],
            confidence: 0.77,
            hits: 4,
            misses: 1,
            created_version: 2,
            source: "reflection",
          },
        ],
        tool_notes: [
          {
            id: "tb-001",
            tool: "date_parse",
            note: "Needs a reference timestamp for relative expressions; without one it silently resolves against today and 'by Friday' drifts a week.",
            evidence: "Two v0 priority misses came from a Friday deadline resolved into the following week.",
            created_version: 1,
          },
        ],
        episodes: [
          { id: "eb-001", text: "v2 train: deadline rule carried both buried-p0 cases; the remaining failure is a mixed-language ticket.", created_version: 2, run_id: "run-b-t2" },
        ],
      },
      applied_lessons: ["l-001", "l-003"],
      versions: [0, 1, 2],
    };
  }

  const v = version ?? BASE_A.current_version;
  return {
    ...AGENTS[0],
    version: v,
    model_strong: "claude-opus-5",
    model_cheap: "claude-haiku-4-5-20251001",
    orchestration: v === 0 ? "single" : "planner_worker",
    routing: v === 0 ? { answer: "strong" } : { plan: "strong", gather: "cheap", answer: "strong" },
    prompt: v === 0 ? PROMPT_V0 : PROMPT_V3,
    tools: TOOLS_A,
    memory: MEMORY_BY_VERSION[v] ?? MEMORY_V3,
    applied_lessons: [],
    versions: [0, 1, 2, 3],
  };
}

/* -------------------------------------------------------------- fix cards */

const trainPR = (v: number) => RUNS_A.find((r) => r.split === "train" && r.version === v)!.pass_rate;
const holdoutPR = (v: number) =>
  RUNS_A.find((r) => r.split === "holdout" && r.version === v)?.pass_rate ?? null;
const trainCost = (v: number) =>
  RUNS_A.find((r) => r.split === "train" && r.version === v)!.total_cost_usd;

export const FIXES: Record<string, FixCard[]> = {
  [AGENT_A]: [
    {
      to_version: 3,
      from_version: 1,
      lever: "memory",
      status: "accepted",
      ts: "2026-09-06T09:34:00Z",
      failing_group: {
        signature: "duplicate_of:null_when_expected",
        tag: "duplicate",
        count: 3,
        case_ids: ["gh-1948", "gh-2044", "gh-2103"],
      },
      hypothesis:
        "duplicate_of comes back null on every duplicate case because list_issues defaults to state=open and the original of a duplicate is already closed. The agent is answering about issues it was never shown.",
      diagnosis:
        "Every duplicate case failed because the search only ever saw open issues. Reflection read the transcript, found the default state parameter in the tool returns, and proposed a tool note plus a rule that cites it. The same version demoted r-004, which had scored 1 hit against 5 misses over six injections.",
      diff_summary: "+2 rules, +1 tool note, 1 rule demoted",
      files_touched: [
        "agents/gh-triage-01/v3/memory/rules.jsonl",
        "agents/gh-triage-01/v3/memory/tool_notes.jsonl",
      ],
      diff_url: "/agents/gh-triage-01/fixes/3/diff",
      before: {
        train_mean: trainPR(1).mean,
        train_std: trainPR(1).std,
        group_pass: 0.111,
        cost_per_run: trainCost(1),
      },
      after: {
        train_mean: trainPR(3).mean,
        train_std: trainPR(3).std,
        group_pass: 0.778,
        holdout_mean: holdoutPR(3)!.mean,
        holdout_std: holdoutPR(3)!.std,
        cost_per_run: trainCost(3),
      },
      memory_entries: [
        {
          id: "r-005",
          kind: "rule",
          change: "added",
          rule: RULES_V3[4].rule,
          scope_keywords: RULES_V3[4].scope_keywords,
          confidence: 0.8,
          evidence_case_ids: RULES_V3[4].evidence_case_ids,
          source: "reflection",
          created_version: 3,
        },
        {
          id: "r-006",
          kind: "rule",
          change: "added",
          rule: RULES_V3[5].rule,
          scope_keywords: RULES_V3[5].scope_keywords,
          confidence: 0.79,
          evidence_case_ids: RULES_V3[5].evidence_case_ids,
          source: "issue",
          created_version: 3,
        },
        {
          id: "t-003",
          kind: "tool_note",
          change: "added",
          tool: "get_file",
          note: TOOL_NOTES_V3[2].note,
          evidence: TOOL_NOTES_V3[2].evidence,
          created_version: 3,
        },
        {
          id: "r-004",
          kind: "rule",
          change: "demoted",
          rule: RULES_V3[3].rule,
          confidence: 0.31,
          text: "1 hit, 5 misses over 6 injections. Kept on disk, no longer injected.",
          created_version: 1,
        },
      ],
    },
    {
      to_version: 2,
      from_version: 1,
      lever: "prompt",
      status: "rejected",
      reason: "regression",
      ts: "2026-09-06T08:11:00Z",
      failing_group: {
        signature: "component_mismatch:tui_vs_session",
        tag: "component",
        count: 4,
        case_ids: ["gh-1877", "gh-1948", "gh-2044", "gh-2103"],
      },
      hypothesis:
        "The component field is wrong whenever the body names more than one file. Instructing the prompt to take the deepest path in the traceback should break the tie.",
      diagnosis:
        "The edit told the agent to always take the deepest path in a stack trace. That is right for crashes and wrong for enhancement requests, which cite a file only as an example. Two cases that had been passing in every repeat started failing, so the gate rejected the candidate.",
      diff_summary: "prompt.md, 1 section rewritten (+6 -2)",
      files_touched: ["agents/gh-triage-01/v2/prompt.md"],
      diff_url: "/agents/gh-triage-01/fixes/2/diff",
      regressed_case_ids: ["gh-1758", "gh-2011"],
      before: {
        train_mean: trainPR(1).mean,
        train_std: trainPR(1).std,
        group_pass: 0.083,
        cost_per_run: trainCost(1),
      },
      after: {
        train_mean: trainPR(2).mean,
        train_std: trainPR(2).std,
        group_pass: 0.25,
        holdout_mean: null,
        holdout_std: null,
        cost_per_run: trainCost(2),
      },
    },
    {
      to_version: 1,
      from_version: 0,
      lever: "memory",
      status: "accepted",
      ts: "2026-09-06T06:57:00Z",
      failing_group: {
        signature: "labels_f1<0.8:missing_platform_label",
        tag: "windows-report",
        count: 5,
        case_ids: ["gh-1731", "gh-1802", "gh-1877", "gh-2044", "gh-2103"],
      },
      hypothesis:
        "v0 never proposes platform:windows. The maintainers apply it to every ConPTY or PowerShell rendering report, and five of the eight label misses in the train set are that one label.",
      diagnosis:
        "Label F1 falls below threshold on Windows terminal reports because the agent never proposes platform:windows, a label whose description it had already fetched and ignored. Reflection wrote four rules and one tool note from the issue bodies and the label descriptions in its own transcript. Each rule carries the case ids it was derived from.",
      diff_summary: "+4 rules, +2 tool notes",
      files_touched: [
        "agents/gh-triage-01/v1/memory/rules.jsonl",
        "agents/gh-triage-01/v1/memory/tool_notes.jsonl",
      ],
      diff_url: "/agents/gh-triage-01/fixes/1/diff",
      before: {
        train_mean: trainPR(0).mean,
        train_std: trainPR(0).std,
        group_pass: 0.0,
        cost_per_run: trainCost(0),
      },
      after: {
        train_mean: trainPR(1).mean,
        train_std: trainPR(1).std,
        group_pass: 0.6,
        holdout_mean: holdoutPR(1)!.mean,
        holdout_std: holdoutPR(1)!.std,
        cost_per_run: trainCost(1),
      },
      memory_entries: [
        ...RULES_V3.filter((r) => r.created_version === 1).map(
          (r): MemoryEntryChange => ({
            id: r.id,
            kind: "rule",
            change: "added",
            rule: r.rule,
            scope_keywords: r.scope_keywords,
            confidence: r.confidence,
            evidence_case_ids: r.evidence_case_ids,
            source: r.source,
            created_version: 1,
          }),
        ),
        ...TOOL_NOTES_V3.filter((t) => t.created_version === 1).map(
          (t): MemoryEntryChange => ({
            id: t.id,
            kind: "tool_note",
            change: "added",
            tool: t.tool,
            note: t.note,
            evidence: t.evidence,
            created_version: 1,
          }),
        ),
      ],
    },
  ],
  [AGENT_B]: [
    {
      to_version: 2,
      from_version: 1,
      lever: "memory",
      status: "accepted",
      ts: "2026-09-06T11:50:00Z",
      failing_group: {
        signature: "priority_mismatch:sarcasm_read_as_p0",
        tag: "sarcasm",
        count: 2,
        case_ids: ["tk-014", "tk-047"],
      },
      hypothesis:
        "Angry-sounding tickets are being graded p0 on tone. Priority should follow what the customer is blocked on.",
      diagnosis:
        "Two sarcastic tickets with no stated impact were graded p0. Reflection separated tone from impact and wrote one rule with both cases as evidence.",
      diff_summary: "+1 rule",
      files_touched: ["agents/ticket-triage-01/v2/memory/rules.jsonl"],
      diff_url: "/agents/ticket-triage-01/fixes/2/diff",
      before: { train_mean: 0.5, train_std: 0.068, group_pass: 0.0, cost_per_run: 0.048 },
      after: {
        train_mean: RUNS_B[1].pass_rate.mean,
        train_std: RUNS_B[1].pass_rate.std,
        group_pass: 0.833,
        holdout_mean: RUNS_B[2].pass_rate.mean,
        holdout_std: RUNS_B[2].pass_rate.std,
        cost_per_run: RUNS_B[1].total_cost_usd,
      },
      memory_entries: [
        {
          id: "rb-002",
          kind: "rule",
          change: "added",
          rule: "Sarcasm markers raise tone, not priority. Grade on what the customer cannot do, not on how they say it.",
          scope_keywords: ["great", "wonderful", "love that", "again"],
          confidence: 0.77,
          evidence_case_ids: ["tk-014", "tk-047"],
          source: "reflection",
          created_version: 2,
        },
      ],
    },
  ],
};

/* ------------------------------------------------------------------ diffs */

export const DIFFS: Record<string, string> = {
  [`${AGENT_A}:1`]: `--- a/agents/gh-triage-01/v0/memory/rules.jsonl
+++ b/agents/gh-triage-01/v1/memory/rules.jsonl
@@ -0,0 +1,4 @@
+{"id":"r-001","rule":"ConPTY / winpty / PowerShell rendering reports get platform:windows alongside bug.","scope_keywords":["conpty","winpty","powershell","windows"],"evidence_case_ids":["gh-1731","gh-1802","gh-1877"],"confidence":0.62,"hits":0,"misses":0,"created_version":1,"source":"reflection"}
+{"id":"r-002","rule":"src/session/ -> session, src/ui/ -> tui, src/provider/ -> providers, scripts/ -> tooling.","scope_keywords":["path","file","src/","traceback"],"evidence_case_ids":["gh-1758","gh-1846","gh-2011"],"confidence":0.7,"hits":0,"misses":0,"created_version":1,"source":"reflection"}
+{"id":"r-003","rule":"A wanted capability with no reproduction steps is enhancement, not bug.","scope_keywords":["would be nice","feature","support for"],"evidence_case_ids":["gh-1903","gh-1975"],"confidence":0.58,"hits":0,"misses":0,"created_version":1,"source":"reflection"}
+{"id":"r-004","rule":"An issue opened by a maintainer is priority p1.","scope_keywords":["maintainer","author"],"evidence_case_ids":["gh-1846"],"confidence":0.44,"hits":0,"misses":0,"created_version":1,"source":"reflection"}
--- a/agents/gh-triage-01/v0/memory/tool_notes.jsonl
+++ b/agents/gh-triage-01/v1/memory/tool_notes.jsonl
@@ -0,0 +1,2 @@
+{"id":"t-001","tool":"list_issues","note":"Paginates at 100 and defaults to state=open. Pass state=all when hunting duplicates.","evidence":"12 of 14 duplicate_of misses used the default state.","created_version":1}
+{"id":"t-002","tool":"list_labels","note":"Returns a description per label. Read it rather than inferring from the name.","evidence":"Label descriptions were fetched in 3 of 42 v0 cases; all 3 had correct label sets.","created_version":1}
`,
  [`${AGENT_A}:2`]: `--- a/agents/gh-triage-01/v1/prompt.md
+++ b/agents/gh-triage-01/v2/prompt.md
@@ -12,8 +12,12 @@
 3. If the body names a file path or contains a traceback, map the path to a
-   component.
+   component. When more than one path appears, always take the deepest path in
+   the traceback: it is the closest to where the failure happened, and the
+   frames above it are almost always framework code that every report shares.
+   Do not weigh the paths mentioned in prose above the ones in the traceback.
+   The deepest frame decides the component on its own.

 4. Before answering duplicate_of, search with state=all.
`,
  [`${AGENT_A}:3`]: `--- a/agents/gh-triage-01/v1/memory/rules.jsonl
+++ b/agents/gh-triage-01/v3/memory/rules.jsonl
@@ -1,4 +1,6 @@
-{"id":"r-004","rule":"An issue opened by a maintainer is priority p1.","confidence":0.44,"hits":0,"misses":0,"created_version":1,"source":"reflection"}
+{"id":"r-004","rule":"An issue opened by a maintainer is priority p1.","confidence":0.31,"hits":1,"misses":5,"created_version":1,"source":"reflection","demoted":true,"demoted_version":3}
+{"id":"r-005","rule":"Before answering duplicate_of, search closed issues as well; the original of a duplicate is usually already closed.","scope_keywords":["duplicate","same as","already reported"],"evidence_case_ids":["gh-1948","gh-2044","gh-2103"],"confidence":0.8,"hits":0,"misses":0,"created_version":3,"source":"reflection"}
+{"id":"r-006","rule":"A traceback containing agent_loop.py belongs to component runtime, not session.","scope_keywords":["traceback","agent_loop","runtime"],"evidence_case_ids":["gh-2204"],"confidence":0.79,"hits":0,"misses":0,"created_version":3,"source":"issue"}
--- a/agents/gh-triage-01/v1/memory/tool_notes.jsonl
+++ b/agents/gh-triage-01/v3/memory/tool_notes.jsonl
@@ -2,3 +2,4 @@
+{"id":"t-003","tool":"get_file","note":"Returns raw file contents and cannot list a directory. Read CODEOWNERS once and reuse it.","evidence":"v1 averaged 4.1 get_file calls per case; v3 averages 1.0.","created_version":3}
`,
  [`${AGENT_B}:2`]: `--- a/agents/ticket-triage-01/v1/memory/rules.jsonl
+++ b/agents/ticket-triage-01/v2/memory/rules.jsonl
@@ -1,1 +1,2 @@
+{"id":"rb-002","rule":"Sarcasm markers raise tone, not priority. Grade on what the customer cannot do.","scope_keywords":["great","wonderful","love that"],"evidence_case_ids":["tk-014","tk-047"],"confidence":0.77,"hits":0,"misses":0,"created_version":2,"source":"reflection"}
`,
};

/* ---------------------------------------------------------------- compare */

const COMPARE: Record<string, CompareResult> = {
  "gh-1731": {
    case_id: "gh-1731",
    expected: {
      labels: ["bug", "platform:windows"],
      component: "tui",
      assignee: "mikelord007",
      duplicate_of: null,
      priority: "p1",
    },
    v0: {
      output: {
        labels: ["bug"],
        component: "session",
        assignee: null,
        duplicate_of: null,
        priority: "p2",
      },
      rules_injected: [],
      tool_calls: 11,
      tokens: 13842,
    },
    current: {
      output: {
        labels: ["bug", "platform:windows"],
        component: "tui",
        assignee: "mikelord007",
        duplicate_of: null,
        priority: "p1",
      },
      rules_injected: [
        { id: "r-001", rule: RULES_V3[0].rule },
        { id: "r-002", rule: RULES_V3[1].rule },
      ],
      tool_calls: 4,
      tokens: 6710,
    },
    current_version: 3,
  },
  "gh-1948": {
    case_id: "gh-1948",
    expected: {
      labels: ["bug", "duplicate"],
      component: "providers",
      assignee: null,
      duplicate_of: 1712,
      priority: "p2",
    },
    v0: {
      output: {
        labels: ["bug"],
        component: "session",
        assignee: null,
        duplicate_of: null,
        priority: "p1",
      },
      rules_injected: [],
      tool_calls: 18,
      tokens: 21440,
    },
    current: {
      output: {
        labels: ["bug", "duplicate"],
        component: "providers",
        assignee: null,
        duplicate_of: 1712,
        priority: "p2",
      },
      rules_injected: [
        { id: "r-002", rule: RULES_V3[1].rule },
        { id: "r-005", rule: RULES_V3[4].rule },
      ],
      tool_calls: 5,
      tokens: 7980,
    },
    current_version: 3,
  },
  "gh-2204": {
    case_id: "gh-2204",
    expected: {
      labels: ["bug", "crash"],
      component: "runtime",
      assignee: "mikelord007",
      duplicate_of: null,
      priority: "p0",
    },
    v0: {
      output: {
        labels: ["bug"],
        component: "session",
        assignee: null,
        duplicate_of: null,
        priority: "p2",
      },
      rules_injected: [],
      tool_calls: 10,
      tokens: 12610,
    },
    current: {
      output: {
        labels: ["bug", "crash"],
        component: "runtime",
        assignee: "mikelord007",
        duplicate_of: null,
        priority: "p0",
      },
      rules_injected: [
        { id: "r-002", rule: RULES_V3[1].rule },
        { id: "r-006", rule: RULES_V3[5].rule },
      ],
      tool_calls: 4,
      tokens: 6890,
    },
    current_version: 3,
  },
  "gh-2044": {
    case_id: "gh-2044",
    expected: {
      labels: ["enhancement", "platform:windows"],
      component: "tooling",
      assignee: null,
      duplicate_of: null,
      priority: "p3",
    },
    v0: {
      output: {
        labels: ["bug"],
        component: "session",
        assignee: null,
        duplicate_of: null,
        priority: "p1",
      },
      rules_injected: [],
      tool_calls: 13,
      tokens: 15980,
    },
    current: {
      output: {
        labels: ["enhancement", "platform:windows"],
        component: "session",
        assignee: null,
        duplicate_of: null,
        priority: "p3",
      },
      rules_injected: [
        { id: "r-001", rule: RULES_V3[0].rule },
        { id: "r-005", rule: RULES_V3[4].rule },
      ],
      tool_calls: 6,
      tokens: 9240,
    },
    current_version: 3,
  },
};

export function compareFor(agentId: string, caseId: string): CompareResult {
  const hit = COMPARE[caseId];
  if (hit) return hit;
  const detail = agentDetail(agentId);
  return {
    case_id: caseId,
    expected: {},
    v0: null,
    current: null,
    current_version: detail.current_version,
  };
}

/* ----------------------------------------------------------------- issues */

export const ISSUES: Issue[] = [
  {
    issue_id: "iss-004",
    agent_id: AGENT_A,
    title: "component_mismatch:tui_vs_session on 3 cases",
    body: "Opened automatically after run-a-t3. Three train cases share the failure signature component_mismatch:tui_vs_session. All three name two file paths in the body.",
    source: "auto",
    status: "open",
    failure_signature: "component_mismatch:tui_vs_session",
    created_ts: "2026-09-06T09:35:00Z",
    linked_case_ids: ["gh-1877", "gh-2044", "gh-2103"],
  },
  {
    issue_id: "iss-003",
    agent_id: AGENT_A,
    title: "Crash reports with an agent_loop.py traceback are routed to session",
    body: "Reported by hand. When a traceback passes through session/manager.py before reaching agent_loop.py, the agent names session as the component. We own agent_loop.py under runtime and the crash always belongs there. This has happened on at least gh-2204 and on two issues that are not in the case set yet.",
    source: "human",
    status: "fixed",
    created_ts: "2026-09-06T08:40:00Z",
    fixed_version: 3,
    linked_case_ids: ["gh-2204"],
  },
  {
    issue_id: "iss-002",
    agent_id: AGENT_A,
    title: "drift:loop on gh-1948",
    body: "Opened automatically after run-a-t0. One case aborted with failure_signature drift:loop: search_issues was called four times with identical arguments before the token budget ran out.",
    source: "auto",
    status: "open",
    failure_signature: "drift:loop",
    created_ts: "2026-09-06T05:30:00Z",
    linked_case_ids: ["gh-1948"],
  },
  {
    issue_id: "iss-001",
    agent_id: AGENT_A,
    title: "Windows terminal reports come back labelled bug only",
    body: "Reported by hand after watching the v0 train run. Every ConPTY and PowerShell rendering report gets bug and nothing else. We apply platform:windows to all of them; the release script filters on that label, so a missing one means the fix ships without a note.",
    source: "human",
    status: "fixed",
    created_ts: "2026-09-06T05:44:00Z",
    fixed_version: 1,
    linked_case_ids: ["gh-1731", "gh-1802"],
  },
  {
    issue_id: "iss-005",
    agent_id: AGENT_B,
    title: "Sarcastic tickets graded p0",
    body: "Reported by hand. A customer wrote 'great, broken again' about a cosmetic problem and it came back p0 with needs_human true.",
    source: "human",
    status: "fixed",
    created_ts: "2026-09-06T11:02:00Z",
    fixed_version: 2,
    linked_case_ids: ["tk-014"],
  },
];

/* --------------------------------------------------------------- playbook */

export const PLAYBOOK: Lesson[] = [
  {
    id: "l-001",
    lever: "memory",
    trigger: "One value is systematically missing from the output across a whole failure group.",
    lesson:
      "Check whether the missing value has a written definition the agent can fetch before touching the prompt. A memory rule that cites the definition and its evidence cases beats a prompt sentence, because it can be demoted later if it stops paying.",
    domain_tags: ["classification", "labels"],
    source_agent_id: AGENT_A,
    source_issue_id: "iss-001",
    ts: "2026-09-06T06:58:00Z",
  },
  {
    id: "l-002",
    lever: "memory",
    trigger: "A tool returns fewer results than the task needs and the agent does not notice.",
    lesson:
      "Record the tool's default parameters as a tool note the first time they cost you a case. Defaults that are invisible in the response are the most expensive kind of missing context.",
    domain_tags: ["tools", "search"],
    source_agent_id: AGENT_A,
    ts: "2026-09-06T09:36:00Z",
  },
  {
    id: "l-003",
    lever: "prompt",
    trigger: "A prompt rewrite fixes the target group and regresses cases outside it.",
    lesson:
      "Scope a prompt edit to the failing group's precondition. An unconditional instruction inherits every case the group does not cover, and the gate will find them.",
    domain_tags: ["prompt", "generalization"],
    source_agent_id: AGENT_A,
    ts: "2026-09-06T08:12:00Z",
  },
  {
    id: "l-004",
    lever: "orchestration",
    trigger: "Tool calls per case stay high after accuracy has stopped improving.",
    lesson:
      "Split gathering from deciding. A cheap model can collect the context a strong model then rules on, and the call count drops before the cost does.",
    domain_tags: ["cost", "orchestration"],
    source_agent_id: AGENT_A,
    ts: "2026-09-06T09:40:00Z",
  },
];

/* --------------------------------------------------------------- insights */

function insightsA(): Insights {
  const passRates = RUNS_A.map((r) => ({
    version: r.version,
    split: r.split,
    ...r.pass_rate,
  }));
  return {
    agent_id: AGENT_A,
    repeats: REPEATS,
    pass_rate_by_version: passRates,
    cost_by_version: RUNS_A.map((r) => ({
      version: r.version,
      split: r.split,
      total_cost_usd: r.total_cost_usd,
      cost_per_run_usd: r.total_cost_usd,
    })),
    latency_by_version: RUNS_A.map((r) => ({
      version: r.version,
      split: r.split,
      p50_latency_ms: r.p50_latency_ms,
      p95_latency_ms: r.p95_latency_ms,
    })),
    fixes_by_lever: { memory: 2, prompt: 1 },
    regressions_caught: 1,
    issues: { open: 2, closed: 2 },
    lessons_count: PLAYBOOK.length,
    drift: {
      count_by_kind: { loop: 3, budget: 2, step_limit: 1 },
      tokens_saved: 41200,
      cases_recovered_by_nudge: 2,
      count_by_version: [
        { version: 0, count: 5 },
        { version: 1, count: 1 },
        { version: 2, count: 0 },
        { version: 3, count: 0 },
      ],
    },
    markers: [
      { version: 0, kind: "issue_opened", label: "iss-001 Windows labels", ts: "2026-09-06T05:44:00Z" },
      { version: 0, kind: "drift_detected", label: "5 drift events", count: 5 },
      {
        version: 1,
        kind: "fix_accepted",
        lever: "memory",
        to_version: 1,
        label: "v1 memory",
        diagnosis: "Four rules and two tool notes written from the transcript; platform:windows now applied.",
      },
      {
        version: 2,
        kind: "fix_rejected",
        lever: "prompt",
        to_version: 2,
        label: "v2 rejected",
        diagnosis: "Deepest-path instruction regressed two stably-passing cases.",
      },
      {
        version: 3,
        kind: "fix_accepted",
        lever: "memory",
        to_version: 3,
        label: "v3 memory",
        diagnosis: "state=all tool note plus two rules; r-004 demoted at 1 hit / 5 misses.",
      },
    ],
    memory_growth_by_version: [
      { version: 0, rules: 0, tool_notes: 0, mean_confidence: null, demotions: 0 },
      { version: 1, rules: 4, tool_notes: 2, mean_confidence: 0.705, demotions: 0 },
      { version: 2, rules: 4, tool_notes: 2, mean_confidence: 0.705, demotions: 0 },
      { version: 3, rules: 5, tool_notes: 3, mean_confidence: 0.82, demotions: 1 },
    ],
    tool_efficiency_by_version: [
      { version: 0, split: "train", tool_calls_per_case: 10.0, tool_errors_per_case: 1.17, tokens_per_case: 11840, latency_ms_per_case: 13908 },
      { version: 1, split: "train", tool_calls_per_case: 7.25, tool_errors_per_case: 0.42, tokens_per_case: 9120, latency_ms_per_case: 10508 },
      { version: 2, split: "train", tool_calls_per_case: 7.5, tool_errors_per_case: 0.33, tokens_per_case: 9260, latency_ms_per_case: 10858 },
      { version: 3, split: "train", tool_calls_per_case: 4.25, tool_errors_per_case: 0.08, tokens_per_case: 6810, latency_ms_per_case: 7233 },
    ],
  };
}

function insightsB(): Insights {
  return {
    agent_id: AGENT_B,
    repeats: REPEATS,
    pass_rate_by_version: RUNS_B.map((r) => ({ version: r.version, split: r.split, ...r.pass_rate })),
    cost_by_version: RUNS_B.map((r) => ({
      version: r.version,
      split: r.split,
      total_cost_usd: r.total_cost_usd,
      cost_per_run_usd: r.total_cost_usd,
    })),
    latency_by_version: RUNS_B.map((r) => ({
      version: r.version,
      split: r.split,
      p50_latency_ms: r.p50_latency_ms,
      p95_latency_ms: r.p95_latency_ms,
    })),
    fixes_by_lever: { memory: 1 },
    regressions_caught: 0,
    issues: { open: 0, closed: 1 },
    lessons_count: PLAYBOOK.length,
    drift: { count_by_kind: {}, tokens_saved: 0, cases_recovered_by_nudge: 0 },
    markers: [
      {
        version: 2,
        kind: "fix_accepted",
        lever: "memory",
        to_version: 2,
        label: "v2 memory",
        diagnosis: "Tone separated from impact; sarcastic tickets no longer graded p0.",
      },
    ],
    memory_growth_by_version: [
      { version: 0, rules: 0, tool_notes: 0, mean_confidence: null, demotions: 0 },
      { version: 1, rules: 1, tool_notes: 1, mean_confidence: 0.83, demotions: 0 },
      { version: 2, rules: 2, tool_notes: 1, mean_confidence: 0.8, demotions: 0 },
    ],
    tool_efficiency_by_version: [
      { version: 0, split: "train", tool_calls_per_case: 2.33, tool_errors_per_case: 0.17, tokens_per_case: 3400, latency_ms_per_case: 3067 },
      { version: 2, split: "train", tool_calls_per_case: 2.0, tool_errors_per_case: 0.0, tokens_per_case: 2900, latency_ms_per_case: 2500 },
    ],
  };
}

export const INSIGHTS: Record<string, Insights> = {
  [AGENT_A]: insightsA(),
  [AGENT_B]: insightsB(),
};

export const COMPARE_DOMAINS: InsightsCompare = {
  domains: [
    {
      agent_id: AGENT_A,
      name: BASE_A.name,
      domain: BASE_A.domain,
      pass_rate_by_version: INSIGHTS[AGENT_A].pass_rate_by_version,
    },
    {
      agent_id: AGENT_B,
      name: BASE_B.name,
      domain: BASE_B.domain,
      pass_rate_by_version: INSIGHTS[AGENT_B].pass_rate_by_version,
    },
  ],
  ablation: {
    domain: "ticket_triage",
    playbook_off: {
      agent_id: "ticket-triage-00",
      holdout: { mean: 0.4167, std: 0.0589, min: 0.3333, max: 0.5 },
    },
    playbook_on: {
      agent_id: AGENT_B,
      holdout: { mean: 0.5833, std: 0.0417, min: 0.5, max: 0.6667 },
    },
    applied_lesson_ids: ["l-001", "l-003"],
  },
};

/* ----------------------------------------------------------------- events */

export const EVENTS: LedgerEvent[] = [
  { id: 1, ts: "2026-09-06T05:02:00Z", kind: "agent_created", agent_id: AGENT_A, agent_version: 0, payload: { goal: BASE_A.goal, domain: "github_triage", evaluator_id: "github_triage", orchestration: "single", applied_lessons: [] } },
  { id: 2, ts: "2026-09-06T05:10:00Z", kind: "run_started", agent_id: AGENT_A, agent_version: 0, run_id: "run-a-t0", payload: { split: "train", case_count: 12, repeats: REPEATS } },
  { id: 3, ts: "2026-09-06T05:21:00Z", kind: "drift_detected", agent_id: AGENT_A, agent_version: 0, run_id: "run-a-t0", payload: { case_id: "gh-1948", repeat: 0, step: 9, kind: "loop", evidence: "search_issues called 4x with identical args", action: "abort", tokens_at_detection: 15800 } },
  { id: 4, ts: "2026-09-06T05:29:00Z", kind: "run_finished", agent_id: AGENT_A, agent_version: 0, run_id: "run-a-t0", payload: { split: "train", repeats: REPEATS, ...RUNS_A[0].pass_rate } },
  { id: 5, ts: "2026-09-06T06:20:00Z", kind: "memory_written", agent_id: AGENT_A, agent_version: 1, payload: { entry_id: "r-001", kind: "rule", source: "reflection", evidence_case_ids: ["gh-1731", "gh-1802", "gh-1877"], version: 1 } },
  { id: 6, ts: "2026-09-06T06:57:00Z", kind: "fix_accepted", agent_id: AGENT_A, agent_version: 1, lever: "memory", payload: { to_version: 1 } },
  { id: 7, ts: "2026-09-06T08:11:00Z", kind: "fix_rejected", agent_id: AGENT_A, agent_version: 2, lever: "prompt", payload: { to_version: 2, reason: "regression", regressed_case_ids: ["gh-1758", "gh-2011"] } },
  { id: 8, ts: "2026-09-06T09:30:00Z", kind: "memory_demoted", agent_id: AGENT_A, agent_version: 3, payload: { entry_id: "r-004", hits: 1, misses: 5, version: 3 } },
  { id: 9, ts: "2026-09-06T09:34:00Z", kind: "fix_accepted", agent_id: AGENT_A, agent_version: 3, lever: "memory", payload: { to_version: 3 } },
];
