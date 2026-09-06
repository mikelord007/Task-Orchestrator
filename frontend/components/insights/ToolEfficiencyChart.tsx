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
  const redundantUnknown = rows.filter((r) => r.redundant === null).map((r) => r.version);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className="text-[11px] text-fg-mute">calls / errors / redundant calls per task (train)</p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.line, strokeWidth: 2 }} />
              <YAxis tick={axisTick} tickLine={false} axisLine={false} width={24} />
              <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
              <Line dataKey="calls" stroke={CHART_COLORS.train} strokeWidth={5} dot={{ r: 3 }} isAnimationActive={false} name="calls/task" />
              <Line dataKey="redundant" stroke={CHART_COLORS.drift} strokeWidth={3} strokeDasharray="3 9" dot={false} isAnimationActive={false} name="redundant/task" />
              <Line dataKey="errors" stroke={CHART_COLORS.fail} strokeWidth={3} dot={{ r: 2 }} isAnimationActive={false} name="errors/task" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        {redundantUnknown.length > 0 ? (
          <p className="mt-1 text-[11px] text-fg-mute">
            redundant/task = — at {versionList(redundantUnknown)} because transcript detail is
            unavailable. Run train with transcript capture enabled to measure it.
          </p>
        ) : null}
      </div>
      <div>
        <p className="text-[11px] text-fg-mute">
          tool-response tokens / latency per task (train){anyEstimated ? " · tokens estimated" : ""}
        </p>
        <div className="mt-1 h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.line, strokeWidth: 2 }} />
              <YAxis yAxisId="tokens" tick={axisTick} tickLine={false} axisLine={false} width={30} />
              <YAxis yAxisId="ms" orientation="right" tick={axisTick} tickLine={false} axisLine={false} width={34} />
              <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
              <Line
                yAxisId="tokens"
                dataKey="tool_tokens"
                stroke={CHART_COLORS.holdout}
                strokeWidth={5}
                strokeDasharray={anyEstimated ? "3 9" : undefined}
                dot={{ r: 2.5 }}
                isAnimationActive={false}
                name={tokensLabel}
                connectNulls
              />
              <Line yAxisId="ms" dataKey="latency_ms" stroke={CHART_COLORS.mute} strokeWidth={3} strokeDasharray="3 9" dot={false} isAnimationActive={false} name="ms/task" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function versionList(versions: number[]): string {
  return [...new Set(versions)].sort((a, b) => a - b).map((v) => `v${v}`).join(", ");
}
