"use client";

import { Bar, BarChart, CartesianGrid, Cell, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DriftStats } from "@/lib/types";
import { compactTokens } from "@/lib/format";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

/**
 * Drift by kind, tokens saved by aborting, tasks recovered by a nudge, and the
 * count falling by version. `byVersion` is supplied by the page: the real
 * backend carries it on `drift.count_by_version`
 * (backend/ledger/metrics.py `drift_stats`); the page falls back to summing
 * `GET /agents/{id}/runs` (train split) when that key is absent, which is
 * what mock data exercises.
 */
export default function DriftPanel({
  drift,
  byVersion,
}: {
  drift: DriftStats;
  byVersion: { version: number; count: number }[];
}) {
  const kindRows = Object.entries(drift.count_by_kind).map(([kind, count]) => ({ kind, count }));
  const hasAny = kindRows.length > 0 || byVersion.length > 0;

  if (!hasAny) {
    return (
      <Empty>
        No drift recorded. Run the train split; watchdog events appear here if a task loops,
        exceeds a budget, or hits the step limit.
      </Empty>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
      <div>
        <p className="text-[11px] text-fg-mute">events by kind</p>
        {kindRows.length === 0 ? (
          <Empty>No drift event yet.</Empty>
        ) : (
          <div className="mt-1 h-32 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={kindRows} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                <XAxis dataKey="kind" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.line, strokeWidth: 2 }} />
                <YAxis tick={axisTick} tickLine={false} axisLine={false} width={24} allowDecimals={false} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" radius={0}>
                  {kindRows.map((r) => (
                    <Cell key={r.kind} fill={CHART_COLORS.drift} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div>
        <p className="text-[11px] text-fg-mute">drift events by version (train)</p>
        {byVersion.length === 0 ? (
          <Empty>Not tracked yet.</Empty>
        ) : (
          <div className="mt-1 h-32 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={byVersion} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.line, strokeWidth: 2 }} />
                <YAxis tick={axisTick} tickLine={false} axisLine={false} width={24} allowDecimals={false} />
                <Tooltip {...tooltipStyle} labelFormatter={(v) => `v${v}`} />
                <Line dataKey="count" stroke={CHART_COLORS.drift} strokeWidth={5} dot={{ r: 3 }} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="mt-1 text-[11px] text-fg-mute">expected to fall as fixes land</p>
      </div>

      <div className="space-y-3">
        <div>
          <p className="text-[11px] text-fg-mute">tokens saved by aborting</p>
          <p className="mt-0.5 text-xl tabular-nums text-fg">{compactTokens(drift.tokens_saved)}</p>
        </div>
        <div>
          <p className="text-[11px] text-fg-mute">tasks recovered by a nudge</p>
          <p className="mt-0.5 text-xl tabular-nums text-fg">{drift.cases_recovered_by_nudge}</p>
        </div>
      </div>
    </div>
  );
}
