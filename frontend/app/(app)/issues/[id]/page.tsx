"use client";

import { useParams } from "next/navigation";
import { useMemo } from "react";
import { fixIssue, getAgent, getIssue, listFixes } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { useJob } from "@/lib/useJob";
import type { IssueStatus } from "@/lib/types";
import { shortTs } from "@/lib/format";
import FixCard from "@/components/FixCard";
import JobBar from "@/components/JobBar";
import { Button, Crumb, Empty, PageHeader, Pill } from "@/components/ui";

const STATUS_TONE: Record<IssueStatus, "pass" | "fail" | "train" | "quiet"> = {
  open: "fail",
  fixing: "train",
  fixed: "pass",
  wontfix: "quiet",
};

export default function IssueDetailPage() {
  const params = useParams<{ id: string }>();
  const issueId = params.id;

  const issue = useAsync(() => getIssue(issueId), [issueId]);
  const agent = useAsync(
    () => (issue.data ? getAgent(issue.data.agent_id) : Promise.resolve(null)),
    [issue.data?.agent_id],
  );
  const fixes = useAsync(
    () => (issue.data ? listFixes(issue.data.agent_id) : Promise.resolve([])),
    [issue.data?.agent_id],
  );
  const job = useJob(() => {
    issue.reload();
    fixes.reload();
  });

  const timeline = useMemo(() => {
    if (!issue.data) return [];
    const linked = new Set(issue.data.linked_case_ids);
    if (linked.size === 0) return [];
    return (fixes.data ?? []).filter((card) =>
      card.failing_group.case_ids.some((id) => linked.has(id)),
    );
  }, [fixes.data, issue.data]);

  if (issue.error) {
    return (
      <div className="mx-auto max-w-[1000px] px-5 py-8 sm:px-8 lg:px-10">
        <Empty>Could not load {issueId}: {issue.error}</Empty>
      </div>
    );
  }
  if (!issue.data) {
    return <div className="px-6 py-5 text-[12px] text-fg-mute">Loading {issueId}…</div>;
  }

  const i = issue.data;
  const isGraderBug = i.tags?.includes("grader-bug");

  return (
    <div className="mx-auto max-w-[1000px] px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
      <div className="mb-2 text-[11px]">
        <Crumb href="/issues">issues</Crumb>
        <span className="text-fg-mute"> / {i.issue_id}</span>
      </div>

      <PageHeader
        title={i.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Pill tone={STATUS_TONE[i.status]}>{i.status}</Pill>
            <Pill tone="quiet">{i.source}</Pill>
            {isGraderBug ? <Pill tone="drift">grader-bug</Pill> : null}
            <span className="text-fg-mute">
              {agent.data?.name ?? i.agent_id} · {shortTs(i.created_ts)}
            </span>
          </span>
        }
        right={
          i.status === "open" && !isGraderBug ? (
            <Button
              variant="primary"
              disabled={job.active}
              onClick={async () => {
                const { job_id } = await fixIssue(i.issue_id);
                job.track(job_id, "Fix issue");
              }}
              title="improver.improve prioritizes the diagnosis group linked to this issue's tasks"
            >
              Fix this
            </Button>
          ) : undefined
        }
      />

      <JobBar handle={job} />

      {isGraderBug ? (
        <p className="mt-3 border-l-2 border-drift/50 pl-3 text-[12px] text-fg-dim">
          Filed as a grader dispute. A grader fix is a separate lever, excluded from this agent's
          improvement curve — it does not go through <b className="text-fg">Fix this</b> here.
        </p>
      ) : null}

      <section className="mt-4 border-t border-line pt-3">
        <h2 className="text-[13px] text-fg">Body</h2>
        <p className="prose-h mt-1 whitespace-pre-wrap text-fg-dim">{i.body}</p>
      </section>

      <section className="mt-4 border-t border-line pt-3">
        <h2 className="text-[13px] text-fg">
          Linked tasks <span className="text-[11px] tabular-nums text-fg-mute">{i.linked_case_ids.length}</span>
        </h2>
        {i.linked_case_ids.length === 0 ? (
          <Empty>
            No task linked yet. A human issue links one once the drafted regression task is
            appended to the train set; an auto issue links every task sharing its failure signature.
          </Empty>
        ) : (
          <p className="mt-1 text-[12px] text-fg-dim">{i.linked_case_ids.join(", ")}</p>
        )}
        {i.failure_signature ? (
          <p className="mt-1 text-[11px] text-fg-mute">signature: {i.failure_signature}</p>
        ) : null}
      </section>

      <section className="mt-4 border-t border-line pt-3">
        <h2 className="text-[13px] text-fg">
          Fix timeline <span className="text-[11px] tabular-nums text-fg-mute">{timeline.length}</span>
        </h2>
        {fixes.loading ? (
          <p className="mt-1 text-[12px] text-fg-mute">Loading…</p>
        ) : timeline.length === 0 ? (
          <Empty>
            No fix attempt has touched this issue's tasks yet. Press{" "}
            <b className="text-fg">Fix this</b> to run the improver against them.
          </Empty>
        ) : (
          timeline.map((card) => (
            <FixCard key={`${card.to_version}-${card.status}`} card={card} agentId={i.agent_id} />
          ))
        )}
      </section>
    </div>
  );
}
