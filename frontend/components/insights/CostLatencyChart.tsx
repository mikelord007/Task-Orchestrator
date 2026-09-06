"use client";

import { Bar, BarChart, CartesianGrid, Cell, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CostPoint, LatencyPoint } from "@/lib/types";
import { usd } from "@/lib/format";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

/**
 * Cost per run and p50/p95 latency by version (train split). The pass@1-vs-cost
 * scatter was cut under time pressure (PLAN_ADDENDUM.md sec M cut order); the
 * pass-rate band and this chart together still answer whether cost moves with
 * accuracy, just not on one plot.
 */
export default function CostLatencyChart({
  cost,
  latency,
}: {
  cost: CostPoint[];
  latency: LatencyPoint[];
}) {
  const costTrain = cost.filter((c) => (c.split ?? "train") === "train");
  const latencyTrain = latency.filter((l) => (l.split ?? "train") === "train");
  const costRows = costTrain.flatMap((c) =>
    c.cost_per_run === null ? [] : [{ version: c.version, cost: c.cost_per_run }],
  );
  const latencyRows = latencyTrain.filter((l) => l.p50_ms !== null || l.p95_ms !== null);
  const missingCost = costTrain.filter((c) => c.cost_per_run === null).map((c) => c.version);
  const missingP50 = latencyTrain.filter((l) => l.p50_ms === null).map((l) => l.version);
  const missingP95 = latencyTrain.filter((l) => l.p95_ms === null).map((l) => l.version);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className="text-[11px] text-fg-mute">cost per run</p>
        {costRows.length === 0 ? (
          <Empty>
            No cost measurement is available. Run train with cost reporting enabled to populate
            this chart.
          </Empty>
        ) : (
          <>
            <div className="mt-1 h-40 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={costRows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                  <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={34} tickFormatter={(v) => usd(v)} />
                  <Tooltip {...tooltipStyle} formatter={(v: number) => usd(v)} labelFormatter={(v) => `v${v}`} />
                  <Bar dataKey="cost" radius={[2, 2, 0, 0]}>
                    {costRows.map((r) => (
                      <Cell key={r.version} fill={CHART_COLORS.train} fillOpacity={0.75} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            {missingCost.length > 0 ? (
              <UnknownNote>
                cost = — at {versionList(missingCost)}. Run train with cost reporting enabled to
                measure it.
              </UnknownNote>
            ) : null}
          </>
        )}
      </div>

      <div>
        <p className="text-[11px] text-fg-mute">p50 / p95 latency (ms)</p>
        {latencyRows.length === 0 ? (
          <Empty>
            No latency measurement is available. Run train with latency reporting enabled to
            populate this chart.
          </Empty>
        ) : (
          <>
            <div className="mt-1 h-40 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={latencyRows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                  <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={34} />
                  <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
                  <Line dataKey="p50_ms" stroke={CHART_COLORS.pass} strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} name="p50" />
                  <Line dataKey="p95_ms" stroke={CHART_COLORS.mute} strokeWidth={1.5} strokeDasharray="3 3" dot={{ r: 2 }} isAnimationActive={false} name="p95" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {missingP50.length > 0 || missingP95.length > 0 ? (
              <UnknownNote>
                {[missingP50.length > 0 ? `p50 = — at ${versionList(missingP50)}` : null,
                  missingP95.length > 0 ? `p95 = — at ${versionList(missingP95)}` : null]
                  .filter(Boolean)
                  .join(" · ")}
                . Run train with latency reporting enabled to measure the missing values.
              </UnknownNote>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function versionList(versions: number[]): string {
  return [...new Set(versions)].sort((a, b) => a - b).map((v) => `v${v}`).join(", ");
}

function UnknownNote({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-[11px] text-fg-mute">{children}</p>;
}
