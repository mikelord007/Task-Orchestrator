"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import {
  getAgent,
  getAgentVersion,
  improveAgent,
  listFixes,
  listRuns,
  LIVE_MODEL_CALLS,
  runAgent,
} from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { useJob } from "@/lib/useJob";
import FixCard from "@/components/FixCard";
import JobBar from "@/components/JobBar";
import Stat from "@/components/Stat";
import MemoryTab from "@/components/agent/MemoryTab";
import PromptTab from "@/components/agent/PromptTab";
import RunsTab from "@/components/agent/RunsTab";
import { Button, Crumb, Empty, PageHeader, Pill, Td, Th } from "@/components/ui";

const TABS = ["prompt", "tools", "memory", "history", "fixes"] as const;
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
  const requestedTab = search.get("tab");
  const tab: Tab =
    requestedTab === "runs"
      ? "history"
      : TABS.includes(requestedTab as Tab)
        ? (requestedTab as Tab)
        : "history";

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
      <div className="mx-auto max-w-[1440px] px-5 py-8 sm:px-8 lg:px-10">
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
  const latestTrain = a.latest_train;
  const latestHoldout = a.latest_holdout;

  const counts: Record<Tab, number | null> = {
    prompt: null,
    tools: a.tools.length,
    memory: a.memory.rules.length + a.memory.tool_notes.length + a.memory.episodes.length,
    history: runs.data?.length ?? null,
    fixes: fixes.data?.length ?? null,
  };

  return (
    <div className="mx-auto max-w-[1440px] px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
      <div className="mb-2 text-[11px]">
        <Crumb href="/agents">agents</Crumb>
        <span className="text-fg-mute"> / {a.agent_id}</span>
      </div>

      <PageHeader
        title={
          <span className="flex flex-wrap items-baseline gap-3">
            {a.name}
            <span className="text-[12px] text-fg-mute">{a.domain}</span>
            <Pill tone="quiet" title={a.orchestration_reason ?? undefined}>
              {a.orchestration}
            </Pill>
          </span>
        }
        subtitle={
          <>
            <span className="prose-h block">{a.goal}</span>
            {a.orchestration_reason ? (
              <span className="prose-h mt-1 block text-fg-mute">{a.orchestration_reason}</span>
            ) : null}
          </>
        }
        right={
          <div className="flex flex-wrap items-start gap-6">
            <Stat label={`train pass@1 (v${a.current_version})`} rate={latestTrain} tone="train" />
            <Stat label={`holdout pass@1 (v${a.current_version})`} rate={latestHoldout} tone="holdout" />
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
              className={`border px-2 py-1 font-mono text-[10px] font-bold uppercase ${
                v === shownVersion
                  ? "border-fg bg-fg text-ink-900"
                  : "border-line text-fg-mute hover:border-[#ff9783] hover:text-[#ff9783]"
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
            className="ml-2 font-mono text-[#ff563c] hover:text-[#ff9783] hover:underline"
          >
            compare a task
          </Link>
          <Link href={`/insights?agent=${agentId}`} className="font-mono text-[#ff563c] hover:text-[#ff9783] hover:underline">
            insights
          </Link>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            disabled={job.active || !LIVE_MODEL_CALLS}
            onClick={async () => {
              const { run_id } = await runAgent(agentId, { split: "train" });
              job.track(run_id, "Run train");
              runs.reload();
            }}
          >
            Run train
          </Button>
          <Button
            disabled={job.active || !LIVE_MODEL_CALLS}
            onClick={async () => {
              const { run_id } = await runAgent(agentId, { split: "holdout" });
              job.track(run_id, "Run holdout");
              runs.reload();
            }}
            title={
              LIVE_MODEL_CALLS
                ? "Holdout is never shown to the improver; it is only run for reporting."
                : "Unavailable: no model provider credentials are configured"
            }
          >
            Run holdout
          </Button>
          <Button
            variant="primary"
            disabled={job.active || !LIVE_MODEL_CALLS}
            onClick={async () => {
              const { job_id } = await improveAgent(agentId, { max_attempts: 3 });
              job.track(job_id, "Improve");
            }}
            title={
              LIVE_MODEL_CALLS
                ? "Diagnose the top failure groups, patch one lever, gate the result."
                : "Unavailable: no model provider credentials are configured"
            }
          >
            Improve
          </Button>
        </div>
      </div>

      <JobBar handle={job} />

      <nav className="mt-6 flex gap-5 overflow-x-auto border-b-2 border-line-soft">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setParam("tab", t)}
            aria-current={t === tab ? "page" : undefined}
            className={`-mb-px border-b-2 px-1 py-2.5 font-mono text-[11px] font-bold uppercase tracking-[0.06em] ${
              t === tab ? "border-fg text-fg" : "border-transparent text-fg-mute hover:text-[#ff9783]"
            }`}
          >
            {t}
            {counts[t] !== null ? (
              <span className="ml-1.5 text-[11px] tabular-nums text-fg-mute">{counts[t]}</span>
            ) : null}
          </button>
        ))}
      </nav>

      <div className="overflow-x-auto pt-4">
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

        {tab === "history" ? (
          runs.loading ? (
            <p className="text-[12px] text-fg-mute">Loading history…</p>
          ) : runs.error ? (
            <Empty>Could not load run history: {runs.error}</Empty>
          ) : (
            <RunsTab
              runs={runs.data ?? []}
              agentId={agentId}
              ruleText={ruleText}
              onTerminal={runs.reload}
            />
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
