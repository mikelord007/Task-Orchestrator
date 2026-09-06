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

  if (costTrain.length === 0) {
    return <Empty>No cost recorded yet. It appears once a split has been run.</Empty>;
  }

  const costRows = costTrain.map((c) => ({ version: c.version, cost: c.cost_per_run }));
  const latencyRows = latencyTrain.map((l) => ({ version: l.version, p50: l.p50_ms, p95: l.p95_ms }));

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className="text-[11px] text-fg-mute">cost per run</p>
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
      </div>

      <div>
        <p className="text-[11px] text-fg-mute">p50 / p95 latency (ms)</p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={latencyRows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
              <YAxis tick={axisTick} tickLine={false} axisLine={false} width={34} />
              <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
              <Line dataKey="p50" stroke={CHART_COLORS.pass} strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} name="p50" />
              <Line dataKey="p95" stroke={CHART_COLORS.mute} strokeWidth={1.5} strokeDasharray="3 3" dot={{ r: 2 }} isAnimationActive={false} name="p95" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
