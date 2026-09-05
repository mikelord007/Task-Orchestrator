"use client";

import { CartesianGrid, Line, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { InsightsCompare } from "@/lib/types";
import { pct } from "@/lib/format";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

const SERIES_COLOR = [CHART_COLORS.train, CHART_COLORS.holdout, CHART_COLORS.pass, CHART_COLORS.drift];

/** Every domain's train pass@1 band side by side, plus the playbook ablation if it exists. */
export default function DomainComparison({ compare }: { compare: InsightsCompare | null }) {
  if (!compare || compare.domains.length === 0) {
    return <Empty>No agents to compare yet. Create a second domain's agent to populate this.</Empty>;
  }

  const versions = Array.from(
    new Set(compare.domains.flatMap((d) => d.pass_at_1_by_version.map((p) => p.version))),
  ).sort((a, b) => a - b);
  const rows = versions.map((version) => {
    const row: Record<string, number | undefined> = { version };
    for (const d of compare.domains) {
      const point = d.pass_at_1_by_version.find((p) => p.version === version && p.split === "train");
      row[d.agent_id] = point?.mean;
    }
    return row;
  });

  return (
    <div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 4, right: 24, left: -18, bottom: 0 }}>
            <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
            <XAxis dataKey="version" tickFormatter={(v) => `v${v}`} tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} />
            <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}`} tick={axisTick} tickLine={false} axisLine={false} width={28} />
            <Tooltip {...tooltipStyle} formatter={(v: number) => `${(v * 100).toFixed(1)}`} labelFormatter={(v) => `v${v}`} />
            {compare.domains.map((d, i) => (
              <Line
                key={d.agent_id}
                dataKey={d.agent_id}
                name={`${d.name} (${d.domain})`}
                stroke={SERIES_COLOR[i % SERIES_COLOR.length]}
                strokeWidth={2}
                dot={{ r: 2.5 }}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-fg-mute">train pass@1 by version, one line per agent</p>

      {compare.ablation ? (
        <div className="mt-3 border-t border-line pt-2">
          <p className="text-[11px] text-fg-mute">
            playbook ablation · {compare.ablation.domain} · v0 holdout pass@1
          </p>
          <div className="mt-1 flex gap-6 text-[12px]">
            <span>
              <span className="text-fg-mute">playbook off </span>
              <span className="tabular-nums text-fg">
                {pct(compare.ablation.playbook_off.holdout.mean)} ± {pct(compare.ablation.playbook_off.holdout.std)}
              </span>
            </span>
            <span>
              <span className="text-fg-mute">playbook on </span>
              <span className="tabular-nums text-pass">
                {pct(compare.ablation.playbook_on.holdout.mean)} ± {pct(compare.ablation.playbook_on.holdout.std)}
              </span>
            </span>
            <span className="text-fg-mute">
              applied lessons: {compare.ablation.applied_lesson_ids.join(", ")}
            </span>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-fg-mute">
          No ablation report yet (reports/ablation.json). Run scripts/playbook_ablation.py to
          produce one.
        </p>
      )}
    </div>
  );
}
