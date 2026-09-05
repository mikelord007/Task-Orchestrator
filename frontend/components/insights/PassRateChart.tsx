"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RatePoint } from "@/lib/types";
import { Empty } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

interface Row {
  version: number;
  trainMean?: number;
  trainMin?: number;
  trainMax?: number;
  trainPowK?: number;
  holdoutMean?: number;
  holdoutMin?: number;
  holdoutMax?: number;
  holdoutPowK?: number;
}

/**
 * pass@1 (solid) and pass^k (dashed) for train and holdout, each pass@1 line
 * shaded from min to max over trials. This is the chart the judges' question
 * 1 and 4 read directly: does the band move up, and does it stay narrow.
 */
export default function PassRateChart({
  trials,
  pass1,
  passK,
}: {
  trials: number;
  pass1: RatePoint[];
  passK: RatePoint[];
}) {
  if (pass1.length === 0) {
    return (
      <Empty>
        No runs recorded for this agent. Run train (and later holdout) from the agent page to
        populate this band.
      </Empty>
    );
  }

  const rows = mergeRows(pass1, passK);

  return (
    <div>
      <p className="text-[11px] text-fg-mute">
        trials = {trials} · solid = pass@1 (mean, shaded min→max) · dashed = pass^k
      </p>
      <div className="mt-2 h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
            <XAxis
              dataKey="version"
              tickFormatter={(v) => `v${v}`}
              tick={axisTick}
              axisLine={{ stroke: CHART_COLORS.grid }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={(v) => `${Math.round(v * 100)}`}
              tick={axisTick}
              axisLine={false}
              tickLine={false}
              width={28}
            />
            <Tooltip
              {...tooltipStyle}
              formatter={(value: number, name: string) => [
                `${(value * 100).toFixed(1)}`,
                name,
              ]}
              labelFormatter={(v) => `v${v}`}
            />
            <Area
              dataKey="trainMax"
              stroke="none"
              fill={CHART_COLORS.train}
              fillOpacity={0.12}
              isAnimationActive={false}
              name="train max"
              connectNulls
            />
            <Area
              dataKey="trainMin"
              stroke="none"
              fill="#080b0f"
              fillOpacity={1}
              isAnimationActive={false}
              name="train min"
              connectNulls
            />
            <Line
              dataKey="trainMean"
              stroke={CHART_COLORS.train}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              isAnimationActive={false}
              name="train pass@1"
              connectNulls
            />
            <Line
              dataKey="trainPowK"
              stroke={CHART_COLORS.train}
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
              name="train pass^k"
              connectNulls
            />
            <Area
              dataKey="holdoutMax"
              stroke="none"
              fill={CHART_COLORS.holdout}
              fillOpacity={0.12}
              isAnimationActive={false}
              name="holdout max"
              connectNulls
            />
            <Area
              dataKey="holdoutMin"
              stroke="none"
              fill="#080b0f"
              fillOpacity={1}
              isAnimationActive={false}
              name="holdout min"
              connectNulls
            />
            <Line
              dataKey="holdoutMean"
              stroke={CHART_COLORS.holdout}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              isAnimationActive={false}
              name="holdout pass@1"
              connectNulls
            />
            <Line
              dataKey="holdoutPowK"
              stroke={CHART_COLORS.holdout}
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
              name="holdout pass^k"
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function mergeRows(pass1: RatePoint[], passK: RatePoint[]): Row[] {
  const versions = Array.from(new Set([...pass1, ...passK].map((p) => p.version))).sort(
    (a, b) => a - b,
  );
  return versions.map((version) => {
    const train1 = pass1.find((p) => p.version === version && p.split === "train");
    const holdout1 = pass1.find((p) => p.version === version && p.split === "holdout");
    const trainK = passK.find((p) => p.version === version && p.split === "train");
    const holdoutK = passK.find((p) => p.version === version && p.split === "holdout");
    return {
      version,
      trainMean: train1?.mean,
      trainMin: train1?.min,
      trainMax: train1?.max,
      trainPowK: trainK?.mean,
      holdoutMean: holdout1?.mean,
      holdoutMin: holdout1?.min,
      holdoutMax: holdout1?.max,
      holdoutPowK: holdoutK?.mean,
    };
  });
}
