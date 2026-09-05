"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { createIssue, listAgents, listIssues } from "@/lib/api";
import type { IssueSource, IssueStatus } from "@/lib/types";
import { shortTs } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Button, Empty, Field, PageHeader, Panel, Pill, Td, Th, inputClass } from "@/components/ui";

const SOURCES: (IssueSource | "all")[] = ["all", "human", "auto"];
const STATUSES: (IssueStatus | "all")[] = ["all", "open", "fixing", "fixed", "wontfix"];

const STATUS_TONE: Record<IssueStatus, "pass" | "fail" | "train" | "quiet"> = {
  open: "fail",
  fixing: "train",
  fixed: "pass",
  wontfix: "quiet",
};

export default function IssuesPage() {
  const issues = useAsync(() => listIssues(), []);
  const agents = useAsync(() => listAgents(), []);
  const [source, setSource] = useState<IssueSource | "all">("all");
  const [status, setStatus] = useState<IssueStatus | "all">("all");
  const [formOpen, setFormOpen] = useState(false);

  const agentName = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of agents.data ?? []) map[a.agent_id] = a.name;
    return map;
  }, [agents.data]);

  const shown = useMemo(
    () =>
      (issues.data ?? [])
        .filter((i) => (source === "all" ? true : i.source === source))
        .filter((i) => (status === "all" ? true : i.status === status)),
    [issues.data, source, status],
  );

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-5">
      <PageHeader
        title="Issues"
        subtitle="Filed by hand, or opened automatically when a run produces a new failure signature. Each one becomes a regression task and, once fixed, a fix card."
        right={
          <Button variant="primary" onClick={() => setFormOpen((v) => !v)}>
            {formOpen ? "Close" : "New issue"}
          </Button>
        }
      />

      {formOpen ? (
        <NewIssueForm
          agents={agents.data ?? []}
          onCreated={() => {
            setFormOpen(false);
            issues.reload();
          }}
        />
      ) : null}

      <Panel title="All issues" meta={issues.data ? `${shown.length} of ${issues.data.length}` : undefined} className="mt-5">
        <div className="flex flex-wrap items-center gap-4 border-b border-line pb-2 text-[11px]">
          <FilterRow label="source" value={source} options={SOURCES} onChange={setSource} />
          <FilterRow label="status" value={status} options={STATUSES} onChange={setStatus} />
        </div>

        {issues.loading ? (
          <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
        ) : issues.error ? (
          <Empty>Could not reach the backend: {issues.error}</Empty>
        ) : shown.length === 0 ? (
          <Empty>
            {issues.data?.length === 0 ? (
              <>
                No issues yet. Press <b className="text-fg">New issue</b> to file one, or run a
                split on an agent — a new failure signature opens one automatically.
              </>
            ) : (
              "No issue matches this filter."
            )}
          </Empty>
        ) : (
          <table className="mt-2 w-full text-[12px]">
            <thead>
              <tr>
                <Th className="w-[8%]">source</Th>
                <Th className="w-[8%]">status</Th>
                <Th className="w-[16%]">agent</Th>
                <Th>title</Th>
                <Th className="w-[13%]">created</Th>
              </tr>
            </thead>
            <tbody>
              {shown.map((issue) => (
                <tr key={issue.issue_id}>
                  <Td>
                    <Pill tone={issue.source === "human" ? "train" : "quiet"}>{issue.source}</Pill>
                  </Td>
                  <Td>
                    <Pill tone={STATUS_TONE[issue.status]}>{issue.status}</Pill>
                  </Td>
                  <Td className="text-fg-dim">{agentName[issue.agent_id] ?? issue.agent_id}</Td>
                  <Td>
                    <Link
                      href={`/issues/${issue.issue_id}`}
                      className="text-fg hover:text-train hover:underline"
                    >
                      {issue.title}
                    </Link>
                    {issue.tags?.includes("grader-bug") ? (
                      <span className="ml-2">
                        <Pill tone="drift">grader-bug</Pill>
                      </span>
                    ) : null}
                  </Td>
                  <Td className="text-fg-mute">{shortTs(issue.created_ts)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function FilterRow<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: T[];
  onChange: (value: T) => void;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-fg-mute">{label}</span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          aria-pressed={value === opt}
          className={`rounded-xs border px-1.5 py-px ${
            value === opt
              ? "border-train/50 text-train"
              : "border-transparent text-fg-mute hover:text-fg-dim"
          }`}
        >
          {opt}
        </button>
      ))}
    </span>
  );
}

function NewIssueForm({
  agents,
  onCreated,
}: {
  agents: { agent_id: string; name: string }[];
  onCreated: () => void;
}) {
  const [agentId, setAgentId] = useState(agents[0]?.agent_id ?? "");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (agents.length === 0) {
    return (
      <Panel title="New issue" className="mt-5">
        <Empty>No agents exist yet. Create one first under Agents.</Empty>
      </Panel>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createIssue({ agent_id: agentId, title, body });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Panel title="New issue" className="mt-5">
      <form onSubmit={submit} className="grid max-w-[720px] gap-4 py-2">
        <Field label="Agent">
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={inputClass}>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What's wrong, in one line."
            className={inputClass}
          />
        </Field>
        <Field
          label="Body"
          hint="Text only. A cheap-model call drafts a regression task from this and appends it to the train set."
        >
          <textarea
            required
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What happened, and what you expected instead."
            className={inputClass}
          />
        </Field>
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy || !title || !body}>
            {busy ? "Filing…" : "File issue"}
          </Button>
          {error ? <span className="text-[12px] text-fail">{error}</span> : null}
        </div>
      </form>
    </Panel>
  );
}
