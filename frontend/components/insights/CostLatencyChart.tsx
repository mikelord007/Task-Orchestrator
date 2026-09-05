"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { CostPoint, LatencyPoint, RatePoint } from "@/lib/types";
import { usd } from "@/lib/format";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

/** Cost per run and p50/p95 latency by version, plus pass@1 vs cost so accuracy and cost read together. */
export default function CostLatencyChart({
  cost,
  latency,
  pass1,
}: {
  cost: CostPoint[];
  latency: LatencyPoint[];
  pass1: RatePoint[];
}) {
  if (cost.length === 0) {
    return <Empty>No cost recorded yet. It appears once a split has been run.</Empty>;
  }

  const costRows = cost
    .filter((c) => c.split === "train")
    .map((c) => ({ version: c.version, cost: c.cost_per_run_usd }));
  const latencyRows = latency
    .filter((l) => l.split === "train")
    .map((l) => ({ version: l.version, p50: l.p50_latency_ms, p95: l.p95_latency_ms }));
  const scatterRows = pass1
    .filter((p) => p.split === "train")
    .map((p) => {
      const c = cost.find((x) => x.version === p.version && x.split === "train");
      return c ? { version: p.version, cost: c.cost_per_run_usd, pass1: p.mean } : null;
    })
    .filter((r): r is { version: number; cost: number; pass1: number } => r !== null)
    .sort((a, b) => a.version - b.version);

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div>
        <p className="text-[11px] text-fg-mute">cost per run (train)</p>
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
        <p className="text-[11px] text-fg-mute">p50 / p95 latency (train, ms)</p>
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

      <div>
        <p className="text-[11px] text-fg-mute">pass@1 vs cost per run (train, by version)</p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} />
              <XAxis
                dataKey="cost"
                type="number"
                tickFormatter={(v) => usd(v)}
                tick={axisTick}
                tickLine={false}
                axisLine={{ stroke: CHART_COLORS.grid }}
                name="cost per run"
              />
              <YAxis
                dataKey="pass1"
                type="number"
                domain={[0, 1]}
                tickFormatter={(v) => `${Math.round(v * 100)}`}
                tick={axisTick}
                tickLine={false}
                axisLine={false}
                width={28}
                name="pass@1"
              />
              <ZAxis range={[60, 60]} />
              <Tooltip
                {...tooltipStyle}
                formatter={(value: number, name: string) =>
                  name === "pass1" ? [`${(value * 100).toFixed(1)}`, "pass@1"] : [usd(value), "cost/run"]
                }
                labelFormatter={() => ""}
              />
              <Scatter data={scatterRows} fill={CHART_COLORS.holdout} isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
