"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  getInsights,
  getInsightsCompare,
  getPlaybook,
  listAgents,
  listFixes,
  listRuns,
} from "@/lib/api";
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
import { Button, Empty, inputClass, PageHeader, Panel, Pill } from "@/components/ui";

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

  const foundAgent = agents.data?.find((a) => a.agent_id === agentId);
  /** `GET /agents` may not carry a display `name` yet; `goal` is always real backend data. */
  const agentName = foundAgent?.name ?? foundAgent?.goal ?? agentId;
  const hasRunHistory = (insights.data?.pass_at_1_by_version.length ?? 0) > 0;

  const driftByVersion = useMemo(() => {
    const byVersion = insights.data?.drift.count_by_version;
    if (byVersion) {
      return Object.entries(byVersion)
        .map(([version, count]) => ({ version: Number(version), count }))
        .sort((a, b) => a.version - b.version);
    }
    return (runs.data ?? [])
      .filter((r) => r.split === "train")
      .slice()
      .sort((a, b) => a.version - b.version)
      .map((r) => ({ version: r.version, count: r.drift_count }));
  }, [insights.data, runs.data]);

  function jumpToFix(toVersion: number) {
    document
      .getElementById(`fix-${toVersion}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="mx-auto max-w-[1360px] space-y-7 px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader
        title="Insights"
        subtitle="Every chart here is a query over the append-only event ledger. Nothing is hardcoded."
        right={
          agents.data && agents.data.length > 0 ? (
            <label className="block w-full sm:w-72">
              <span className="text-[10px] font-medium uppercase tracking-wider text-fg-dim">
                Agent workspace
              </span>
              <select
                value={agentId ?? ""}
                onChange={(e) => router.replace(`/insights?agent=${e.target.value}`)}
                className={`${inputClass} border-fg-mute/50 bg-ink-800`}
              >
                {agents.data.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.name ?? a.goal}
                  </option>
                ))}
              </select>
            </label>
          ) : !agents.loading ? (
            <AgentIdField
              initial={agentId ?? ""}
              onGo={(id) => router.replace(`/insights?agent=${id}`)}
            />
          ) : undefined
        }
      />

      {agents.loading ? (
        <p className="mt-4 text-[12px] text-fg-mute">Loading agents…</p>
      ) : !agentId ? (
        <Empty>
          No agents yet. Create one under Agents, run a split, and its charts appear here — or type
          a known agent id above.
        </Empty>
      ) : (
        <>
          {insights.data?.saturated ? (
            <div className="rounded-lg border border-drift/40 bg-drift/5 px-4 py-4 text-[12px] leading-6 text-drift">
              Capability suite saturated for {agentName}: train pass@1 has held ≥ 95% for two
              consecutive versions. Add harder tasks to the train split before trusting further
              gains here.
            </div>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-line border-t-pass/60 bg-ink-800 p-6">
              <Stat
                label="tasks graduated"
                value={hasRunHistory ? String(insights.data?.graduated_count ?? "—") : "—"}
                tone="pass"
                size="lg"
              />
              <p className="mt-4 text-[11px] leading-5 text-fg-mute">
                Tasks that met the graduation criteria.
              </p>
            </div>
            <div className="rounded-xl border border-line border-t-fg-mute/60 bg-ink-800 p-6">
              <div className="text-[11px] leading-4 text-fg-mute">flagged tasks</div>
              <div className="text-3xl leading-tight tabular-nums text-fg">
                {hasRunHistory ? (insights.data?.flagged_tasks.length ?? "—") : "—"}
              </div>
              <p className="mt-4 text-[11px] leading-5 text-fg-mute">
                Tasks at 0% pass rate for three versions.
              </p>
            </div>
          </div>

          <div className="space-y-5">
            <h2 className="text-[11px] uppercase tracking-[0.16em] text-fg-mute">Performance</h2>
            <Panel title="Pass rate by version" meta={<Pill tone="quiet">pass@1 / pass^k</Pill>}>
              {insights.loading ? (
                <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
              ) : (
                <PassRateChart
                  pass1={insights.data?.pass_at_1_by_version ?? []}
                  passK={insights.data?.pass_pow_k_by_version ?? []}
                  markers={insights.data?.markers ?? []}
                  onJumpToFix={jumpToFix}
                />
              )}
            </Panel>

            <Panel title="Cost and latency">
              {insights.data ? (
                <CostLatencyChart
                  cost={insights.data.cost_by_version}
                  latency={insights.data.latency_by_version}
                />
              ) : (
                <Empty>No runs yet.</Empty>
              )}
            </Panel>
          </div>

          <div className="space-y-5">
            <h2 className="text-[11px] uppercase tracking-[0.16em] text-fg-mute">
              Improvement evidence
            </h2>
            <Panel title="Fixes, regressions and issues">
              {insights.data && hasRunHistory ? (
                <FixesSummary
                  fixesByLever={insights.data.fixes_by_lever}
                  regressionsCaught={insights.data.regressions_caught}
                  issues={insights.data.issues}
                />
              ) : (
                <Empty>
                  No improvement evidence yet. Run the train split, then start an improve attempt to
                  populate fixes, caught regressions, and linked issues.
                </Empty>
              )}
            </Panel>

            <Panel title="Fix cards" meta={fixes.data ? `${fixes.data.length}` : undefined}>
              {fixes.loading ? (
                <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
              ) : (fixes.data?.length ?? 0) === 0 ? (
                <Empty>No improvement attempt yet for {agentName}.</Empty>
              ) : (
                fixes.data!.map((card) => (
                  <FixCard
                    key={`${card.to_version}-${card.status}`}
                    card={card}
                    agentId={agentId}
                  />
                ))
              )}
            </Panel>
          </div>

          <div className="space-y-5">
            <h2 className="text-[11px] uppercase tracking-[0.16em] text-fg-mute">
              Runtime &amp; memory
            </h2>
            <Panel title="Drift">
              {insights.data ? (
                <DriftPanel drift={insights.data.drift} byVersion={driftByVersion} />
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
          </div>

          <div className="space-y-5">
            <h2 className="text-[11px] uppercase tracking-[0.16em] text-fg-mute">
              Tasks &amp; shared learning
            </h2>
            <Panel title="Flagged tasks" meta={<span>0% for 3 versions running</span>}>
              <FlaggedTasks tasks={insights.data?.flagged_tasks ?? []} />
            </Panel>

            <div className="grid items-start gap-5 xl:grid-cols-2">
              <Panel title="Domain comparison">
                <DomainComparison compare={compare.data ?? null} />
              </Panel>

              <Panel
                title="Playbook"
                meta={playbook.data ? `${playbook.data.length} lessons` : undefined}
              >
                <PlaybookPanel lessons={playbook.data ?? []} />
              </Panel>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * `GET /agents` is not wired up yet on every deployment (still merging as of
 * this writing), so this page must stay usable by direct agent id — this
 * text field is the fallback for the agent dropdown while that endpoint is
 * unavailable; once it lands, `agents.data` is non-empty and this never
 * renders.
 */
function AgentIdField({ initial, onGo }: { initial: string; onGo: (agentId: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onGo(value.trim());
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label="Agent ID"
        placeholder="agent id"
        className={`${inputClass} mt-0 w-48`}
      />
      <Button type="submit">Go</Button>
    </form>
  );
}
