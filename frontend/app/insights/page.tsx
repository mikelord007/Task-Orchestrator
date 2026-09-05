"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { getInsights, getInsightsCompare, getPlaybook, listAgents, listFixes, listRuns } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import FixCard from "@/components/FixCard";
import Stat from "@/components/Stat";
import CostLatencyChart from "@/components/insights/CostLatencyChart";
import DomainComparison from "@/components/insights/DomainComparison";
import DriftPanel from "@/components/insights/DriftPanel";
import FixesSummary from "@/components/insights/FixesSummary";
import FlaggedTasks from "@/components/insights/FlaggedTasks";
import MemoryGrowthChart from "@/components/insights/MemoryGrowthChart";
import PassRateChart from "@/components/insights/PassRateChart";
import PlaybookPanel from "@/components/insights/PlaybookPanel";
import ToolEfficiencyChart from "@/components/insights/ToolEfficiencyChart";
import { Empty, PageHeader, Panel, Pill } from "@/components/ui";

export default function InsightsPage() {
  return (
    <Suspense fallback={<div className="px-6 py-5 text-[12px] text-fg-mute">Loading…</div>}>
      <Insights />
    </Suspense>
  );
}

function Insights() {
  const search = useSearchParams();
  const router = useRouter();
  const agents = useAsync(() => listAgents(), []);
  const agentId = search.get("agent");

  useEffect(() => {
    if (!agentId && agents.data && agents.data.length > 0) {
      router.replace(`/insights?agent=${agents.data[0].agent_id}`, { scroll: false });
    }
  }, [agentId, agents.data, router]);

  const insights = useAsync(
    () => (agentId ? getInsights(agentId) : Promise.resolve(null)),
    [agentId],
  );
  const fixes = useAsync(() => (agentId ? listFixes(agentId) : Promise.resolve([])), [agentId]);
  const runs = useAsync(() => (agentId ? listRuns(agentId) : Promise.resolve([])), [agentId]);
  const compare = useAsync(() => getInsightsCompare(), []);
  const playbook = useAsync(() => getPlaybook(), []);

  const agentName = agents.data?.find((a) => a.agent_id === agentId)?.name ?? agentId;
  /** Insights carries no trials field (contracts/api.md); read it off the most recent run instead. */
  const trials = runs.data?.slice(-1)[0]?.trials;

  return (
    <div className="mx-auto max-w-[1360px] px-6 py-5">
      <PageHeader
        title="Insights"
        subtitle="Every chart here is a query over the append-only event ledger. Nothing is hardcoded."
        right={
          agents.data && agents.data.length > 0 ? (
            <select
              value={agentId ?? ""}
              onChange={(e) => router.replace(`/insights?agent=${e.target.value}`)}
              className="rounded-xs border border-line bg-ink-800 px-2 py-1.5 text-[12px] text-fg focus:border-train focus:outline-none"
            >
              {agents.data.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      {agents.loading ? (
        <p className="mt-4 text-[12px] text-fg-mute">Loading agents…</p>
      ) : !agentId ? (
        <Empty>
          No agents yet. Create one under Agents, run a split, and its charts appear here.
        </Empty>
      ) : (
        <>
          {insights.data?.saturated ? (
            <div className="mt-3 border border-drift/40 bg-drift/5 px-3 py-2 text-[12px] text-drift">
              Capability suite saturated for {agentName}: train pass@1 has held ≥ 95% for two
              consecutive versions. Add harder tasks to the train split before trusting further
              gains here.
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-8">
            <Stat
              label="tasks graduated"
              value={String(insights.data?.graduated_count ?? "—")}
              tone="pass"
              size="lg"
            />
            <div className="min-w-[140px]">
              <div className="text-[11px] text-fg-mute">flagged tasks</div>
              <div className="mt-1 text-xl tabular-nums text-fg">
                {insights.data?.flagged_tasks.length ?? "—"}
              </div>
            </div>
          </div>

          <Panel title="Pass rate by version" meta={<Pill tone="quiet">pass@1 / pass^k</Pill>}>
            {insights.loading ? (
              <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
            ) : (
              <PassRateChart
                trials={trials ?? 0}
                pass1={insights.data?.pass_at_1_by_version ?? []}
                passK={insights.data?.pass_pow_k_by_version ?? []}
              />
            )}
          </Panel>

          <Panel title="Cost, latency and pass@1-vs-cost">
            {insights.data ? (
              <CostLatencyChart
                cost={insights.data.cost_by_version}
                latency={insights.data.latency_by_version}
                pass1={insights.data.pass_at_1_by_version}
              />
            ) : (
              <Empty>No runs yet.</Empty>
            )}
          </Panel>

          <Panel title="Fixes, regressions and issues">
            {insights.data ? (
              <FixesSummary
                fixesByLever={insights.data.fixes_by_lever}
                regressionsCaught={insights.data.regressions_caught}
                issues={insights.data.issues}
              />
            ) : (
              <Empty>No fixes yet.</Empty>
            )}
          </Panel>

          <Panel title="Fix cards" meta={fixes.data ? `${fixes.data.length}` : undefined}>
            {fixes.loading ? (
              <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
            ) : (fixes.data?.length ?? 0) === 0 ? (
              <Empty>No improvement attempt yet for {agentName}.</Empty>
            ) : (
              fixes.data!.map((card) => (
                <FixCard key={`${card.to_version}-${card.status}`} card={card} agentId={agentId} />
              ))
            )}
          </Panel>

          <Panel title="Drift">
            {insights.data ? (
              <DriftPanel drift={insights.data.drift} runs={runs.data ?? []} />
            ) : (
              <Empty>No data yet.</Empty>
            )}
          </Panel>

          <Panel title="Memory growth">
            {insights.data ? (
              <MemoryGrowthChart points={insights.data.memory_by_version} />
            ) : (
              <Empty>No data yet.</Empty>
            )}
          </Panel>

          <Panel title="Tool-usage efficiency">
            {insights.data ? (
              <ToolEfficiencyChart points={insights.data.tool_stats_by_version} />
            ) : (
              <Empty>No data yet.</Empty>
            )}
          </Panel>

          <Panel title="Flagged tasks" meta={<span>0% for 3 versions running</span>}>
            <FlaggedTasks tasks={insights.data?.flagged_tasks ?? []} />
          </Panel>

          <Panel title="Domain comparison">
            <DomainComparison compare={compare.data ?? null} />
          </Panel>

          <Panel title="Playbook" meta={playbook.data ? `${playbook.data.length} lessons` : undefined}>
            <PlaybookPanel lessons={playbook.data ?? []} />
          </Panel>
        </>
      )}
    </div>
  );
}
