"use client";

import { CartesianGrid, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ToolStatsByVersionPoint } from "@/lib/types";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

/**
 * Tool calls, errors, redundant calls and latency per task — all expected to
 * fall as the tools lever lands (addendum section K). This is the chart that
 * answers "does it balance cost and speed" alongside the cost panel.
 */
export default function ToolEfficiencyChart({ points }: { points: ToolStatsByVersionPoint[] }) {
  const rows = points.filter((p) => p.split === "train");
  if (rows.length === 0) {
    return <Empty>No tool-call stats yet. They appear once a train run completes.</Empty>;
  }
  const anyEstimated = rows.some((r) => r.tool_tokens_estimated);
  const tokensLabel = anyEstimated ? "tokens/task (est.)" : "tokens/task";

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className="text-[11px] text-fg-mute">calls / errors / redundant calls per task (train)</p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
              <YAxis tick={axisTick} tickLine={false} axisLine={false} width={24} />
              <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
              <Line dataKey="calls" stroke={CHART_COLORS.train} strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} name="calls/task" />
              <Line dataKey="redundant" stroke={CHART_COLORS.drift} strokeWidth={1.5} strokeDasharray="3 3" dot={{ r: 2 }} isAnimationActive={false} name="redundant/task" />
              <Line dataKey="errors" stroke={CHART_COLORS.fail} strokeWidth={1.5} dot={{ r: 2 }} isAnimationActive={false} name="errors/task" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div>
        <p className="text-[11px] text-fg-mute">
          tool-response tokens / latency per task (train){anyEstimated ? " · tokens estimated" : ""}
        </p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
              <YAxis yAxisId="tokens" tick={axisTick} tickLine={false} axisLine={false} width={30} />
              <YAxis yAxisId="ms" orientation="right" tick={axisTick} tickLine={false} axisLine={false} width={34} />
              <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
              <Line
                yAxisId="tokens"
                dataKey="tool_tokens"
                stroke={CHART_COLORS.holdout}
                strokeWidth={2}
                strokeDasharray={anyEstimated ? "4 2" : undefined}
                dot={{ r: 2.5 }}
                isAnimationActive={false}
                name={tokensLabel}
                connectNulls
              />
              <Line yAxisId="ms" dataKey="latency_ms" stroke={CHART_COLORS.pass} strokeWidth={1.5} strokeDasharray="3 3" dot={{ r: 2 }} isAnimationActive={false} name="ms/task" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
