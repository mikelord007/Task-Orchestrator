"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { getAgent, getAgentVersion, improveAgent, listFixes, listRuns, runAgent } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { useJob } from "@/lib/useJob";
import FixCard from "@/components/FixCard";
import JobBar from "@/components/JobBar";
import Stat from "@/components/Stat";
import MemoryTab from "@/components/agent/MemoryTab";
import PromptTab from "@/components/agent/PromptTab";
import RunsTab from "@/components/agent/RunsTab";
import { Button, Crumb, Empty, PageHeader, Pill, Td, Th } from "@/components/ui";

const TABS = ["prompt", "tools", "memory", "runs", "fixes"] as const;
type Tab = (typeof TABS)[number];

export default function AgentPage() {
  return (
    <Suspense fallback={<div className="px-6 py-5 text-[12px] text-fg-mute">Loading…</div>}>
      <AgentDetail />
    </Suspense>
  );
}

function AgentDetail() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const agentId = params.id;

  const versionParam = search.get("version");
  const tab = (search.get("tab") as Tab) ?? "runs";

  const agent = useAsync(
    () =>
      versionParam === null
        ? getAgent(agentId)
        : getAgentVersion(agentId, Number(versionParam)),
    [agentId, versionParam],
  );
  const runs = useAsync(() => listRuns(agentId), [agentId]);
  const fixes = useAsync(() => listFixes(agentId), [agentId]);

  const job = useJob(() => {
    runs.reload();
    fixes.reload();
    agent.reload();
  });

  const ruleText = useMemo(() => {
    const map: Record<string, string> = {};
    for (const rule of agent.data?.memory.rules ?? []) map[rule.id] = rule.rule;
    return map;
  }, [agent.data]);

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(search.toString());
    if (value === null) next.delete(key);
    else next.set(key, value);
    router.replace(`/agents/${agentId}?${next.toString()}`, { scroll: false });
  }

  if (agent.error) {
    return (
      <div className="mx-auto max-w-[1360px] px-6 py-5">
        <Empty>Could not load {agentId}: {agent.error}</Empty>
      </div>
    );
  }
  if (!agent.data) {
    return <div className="px-6 py-5 text-[12px] text-fg-mute">Loading {agentId}…</div>;
  }

  const a = agent.data;
  const versions = a.versions ?? Array.from({ length: a.current_version + 1 }, (_, i) => i);
  const shownVersion = a.version;
  const latestTrain =
    runs.data?.filter((r) => r.split === "train" && r.version === a.current_version).slice(-1)[0]
      ?.pass_rate ?? a.latest_train;
  const latestHoldout =
    runs.data?.filter((r) => r.split === "holdout" && r.version === a.current_version).slice(-1)[0]
      ?.pass_rate ?? a.latest_holdout;

  const counts: Record<Tab, number | null> = {
    prompt: null,
    tools: a.tools.length,
    memory: a.memory.rules.length + a.memory.tool_notes.length + a.memory.episodes.length,
    runs: runs.data?.length ?? null,
    fixes: fixes.data?.length ?? null,
  };

  return (
    <div className="mx-auto max-w-[1360px] px-6 py-5">
      <div className="mb-2 text-[11px]">
        <Crumb href="/agents">agents</Crumb>
        <span className="text-fg-mute"> / {a.agent_id}</span>
      </div>

      <PageHeader
        title={
          <span className="flex flex-wrap items-baseline gap-3">
            {a.name}
            <span className="text-[12px] text-fg-mute">{a.domain}</span>
            <Pill tone="quiet">{a.orchestration}</Pill>
          </span>
        }
        subtitle={<span className="prose-h block">{a.goal}</span>}
        right={
          <div className="flex flex-wrap items-start gap-6">
            <Stat label={`train (v${a.current_version})`} rate={latestTrain} tone="train" />
            <Stat label={`holdout (v${a.current_version})`} rate={latestHoldout} tone="holdout" />
          </div>
        }
      />

      <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="text-fg-mute">version</span>
          {versions.map((v) => (
            <button
              key={v}
              onClick={() => setParam("version", String(v))}
              aria-pressed={v === shownVersion}
              className={`rounded-xs border px-1.5 py-px ${
                v === shownVersion
                  ? "border-train/50 text-train"
                  : "border-line text-fg-mute hover:text-fg-dim"
              }`}
              title={v === a.current_version ? "Current version" : `Snapshot v${v}`}
            >
              v{v}
              {v === a.current_version ? "*" : ""}
            </button>
          ))}
          <span className="text-fg-mute">* current</span>
          <Link
            href={`/agents/${agentId}/compare`}
            className="ml-2 text-fg-mute hover:text-train hover:underline"
          >
            compare a case
          </Link>
          <Link href={`/insights?agent=${agentId}`} className="text-fg-mute hover:text-train hover:underline">
            insights
          </Link>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            disabled={job.active}
            onClick={async () => {
              const { run_id } = await runAgent(agentId, { split: "train" });
              job.track(run_id, "Run train");
            }}
          >
            Run train
          </Button>
          <Button
            disabled={job.active}
            onClick={async () => {
              const { run_id } = await runAgent(agentId, { split: "holdout" });
              job.track(run_id, "Run holdout");
            }}
            title="Holdout is never shown to the improver; it is only run for reporting."
          >
            Run holdout
          </Button>
          <Button
            variant="primary"
            disabled={job.active}
            onClick={async () => {
              const { job_id } = await improveAgent(agentId, { max_attempts: 3 });
              job.track(job_id, "Improve");
            }}
            title="Diagnose the top failure groups, patch one lever, gate the result."
          >
            Improve
          </Button>
        </div>
      </div>

      <JobBar handle={job} />

      <nav className="mt-4 flex gap-5 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setParam("tab", t)}
            aria-current={t === tab ? "page" : undefined}
            className={`-mb-px border-b py-1.5 text-[12px] ${
              t === tab ? "border-train text-fg" : "border-transparent text-fg-mute hover:text-fg-dim"
            }`}
          >
            {t}
            {counts[t] !== null ? (
              <span className="ml-1.5 text-[11px] tabular-nums text-fg-mute">{counts[t]}</span>
            ) : null}
          </button>
        ))}
      </nav>

      <div className="pt-4">
        {tab === "prompt" ? <PromptTab prompt={a.prompt} /> : null}

        {tab === "tools" ? (
          a.tools.length === 0 ? (
            <Empty>
              This version has no tools. Pick them on the New agent form, or let the improver add
              one with the tools lever.
            </Empty>
          ) : (
            <table className="w-full max-w-[1100px] text-[12px]">
              <thead>
                <tr>
                  <Th className="w-[18%]">tool</Th>
                  <Th>description</Th>
                </tr>
              </thead>
              <tbody>
                {a.tools.map((tool) => (
                  <tr key={tool.name}>
                    <Td className="text-fg">{tool.name}</Td>
                    <Td className="text-fg-dim">
                      <span className="prose-h block">{tool.description}</span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}

        {tab === "memory" ? <MemoryTab memory={a.memory} /> : null}

        {tab === "runs" ? (
          runs.loading ? (
            <p className="text-[12px] text-fg-mute">Loading runs…</p>
          ) : (
            <RunsTab runs={runs.data ?? []} agentId={agentId} ruleText={ruleText} />
          )
        ) : null}

        {tab === "fixes" ? (
          fixes.loading ? (
            <p className="text-[12px] text-fg-mute">Loading fixes…</p>
          ) : (fixes.data?.length ?? 0) === 0 ? (
            <Empty>
              No improvement attempts yet. Press <b className="text-fg">Improve</b>: each attempt
              writes a card here, accepted or rejected.
            </Empty>
          ) : (
            <div>
              <p className="pb-1 text-[11px] text-fg-mute">
                Newest first. A rejected card is an attempt the gate refused, kept because a caught
                regression is a result.
              </p>
              {fixes.data!.map((card) => (
                <FixCard key={`${card.to_version}-${card.status}`} card={card} agentId={agentId} />
              ))}
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}
