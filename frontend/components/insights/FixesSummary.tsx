"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Lever } from "@/lib/types";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

const LEVER_COLOR: Record<Lever, string> = {
  memory: CHART_COLORS.pass,
  tools: CHART_COLORS.train,
  prompt: CHART_COLORS.holdout,
  orchestration: CHART_COLORS.mute,
  routing: CHART_COLORS.drift,
  grader: CHART_COLORS.fail,
};

/** Fixes by lever, regressions caught, and issue counts — the mechanism, not only the curve. */
export default function FixesSummary({
  fixesByLever,
  regressionsCaught,
  issues,
}: {
  fixesByLever: Partial<Record<Lever, number>>;
  regressionsCaught: number;
  issues: { open: number; closed: number };
}) {
  const rows = Object.entries(fixesByLever).map(([lever, count]) => ({ lever, count }));

  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr_1fr]">
      <div>
        <p className="text-[11px] text-fg-mute">accepted fixes by lever</p>
        {rows.length === 0 ? (
          <Empty>No accepted fix yet.</Empty>
        ) : (
          <div className="mt-1 h-32 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
                <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
                <XAxis type="number" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART_COLORS.grid }} allowDecimals={false} />
                <YAxis dataKey="lever" type="category" tick={axisTick} tickLine={false} axisLine={false} width={78} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" radius={[0, 2, 2, 0]}>
                  {rows.map((r) => (
                    <Cell key={r.lever} fill={LEVER_COLOR[r.lever as Lever] ?? CHART_COLORS.mute} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div>
        <p className="text-[11px] text-fg-mute">regressions caught</p>
        <p className="mt-1 text-2xl tabular-nums text-fg">{regressionsCaught}</p>
        <p className="mt-1 text-[11px] text-fg-mute">by the pass^k gate before landing</p>
      </div>

      <div>
        <p className="text-[11px] text-fg-mute">issues</p>
        <p className="mt-1 text-2xl tabular-nums text-fg">
          <span className="text-fail">{issues.open}</span>
          <span className="text-fg-mute"> open / </span>
          <span className="text-pass">{issues.closed}</span>
          <span className="text-fg-mute"> closed</span>
        </p>
      </div>
    </div>
  );
}
