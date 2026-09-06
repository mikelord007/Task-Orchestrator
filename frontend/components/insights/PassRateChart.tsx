"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Marker, RatePoint } from "@/lib/types";
import { Empty, Pill } from "@/components/ui";
import { CHART_COLORS, axisTick, tooltipStyle } from "./chart-common";

interface Row {
  version: number;
  trainMean?: number;
  trainErr?: [number, number];
  trainBandLow?: number;
  trainBandHeight?: number;
  trainPowK?: number;
  trainPowKErr?: [number, number];
  trainPowKBandLow?: number;
  trainPowKBandHeight?: number;
  holdoutMean?: number;
  holdoutErr?: [number, number];
  holdoutBandLow?: number;
  holdoutBandHeight?: number;
  holdoutPowK?: number;
  holdoutPowKErr?: [number, number];
  holdoutPowKBandLow?: number;
  holdoutPowKBandHeight?: number;
}

const MARKER_LINE_COLOR: Record<Marker["kind"], string> = {
  issue_opened: CHART_COLORS.drift,
  fix_accepted: CHART_COLORS.pass,
  fix_rejected: CHART_COLORS.fail,
  memory_demoted: CHART_COLORS.holdout,
  drift_cluster: CHART_COLORS.mute,
};

const MARKER_TONE: Record<
  Marker["kind"],
  "neutral" | "pass" | "fail" | "train" | "holdout" | "drift" | "quiet"
> = {
  issue_opened: "drift",
  fix_accepted: "pass",
  fix_rejected: "fail",
  memory_demoted: "holdout",
  drift_cluster: "quiet",
};

const MARKER_LABEL: Record<Marker["kind"], string> = {
  issue_opened: "issue",
  fix_accepted: "fix accepted",
  fix_rejected: "fix rejected",
  memory_demoted: "rule demoted",
  drift_cluster: "drift",
};

/** Priority for the vertical reference line's color when several markers share a version. */
const LINE_PRIORITY: Marker["kind"][] = [
  "fix_rejected",
  "fix_accepted",
  "memory_demoted",
  "issue_opened",
  "drift_cluster",
];

/**
 * pass@1 (solid) and pass^k (dashed) for train and holdout: a shaded ±1σ band
 * under the mean line (`Area`) plus min/max whiskers (`ErrorBar`) — this is
 * the chart the judges' question 1 and 4 read directly: does the band move
 * up, and does it stay narrow. Vertical lines mark versions with an issue,
 * fix or drift cluster; the chip strip below is what carries the actual
 * hover text (lever + hypothesis) and the click-through to the fix card,
 * since Recharts has no reliable hover surface nested this deep in an SVG.
 */
export default function PassRateChart({
  pass1,
  passK,
  markers = [],
  onJumpToFix,
}: {
  pass1: RatePoint[];
  passK: RatePoint[];
  markers?: Marker[];
  onJumpToFix?: (toVersion: number) => void;
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
  const markersByVersion = groupByVersion(markers);
  const trials = trialSummary(pass1, passK);

  return (
    <div>
      <p className="text-[11px] text-fg-mute">
        {trials} · solid = pass@1 · dashed = pass^k · shaded = mean ±1σ · whiskers = min/max
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
              formatter={(value: unknown, name: string) =>
                typeof value === "number" ? [`${(value * 100).toFixed(1)}`, name] : ["", name]
              }
              labelFormatter={(v) => `v${v}`}
            />
            {Array.from(markersByVersion.entries()).map(([version, ms]) => (
              <ReferenceLine
                key={`marker-${version}`}
                x={version}
                stroke={lineColorFor(ms)}
                strokeDasharray="2 2"
                strokeOpacity={0.6}
              />
            ))}
            <Area
              dataKey="trainBandLow"
              stackId="trainBand"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="trainBandHeight"
              stackId="trainBand"
              stroke="none"
              fill={CHART_COLORS.train}
              fillOpacity={0.15}
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="trainPowKBandLow"
              stackId="trainPowKBand"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="trainPowKBandHeight"
              stackId="trainPowKBand"
              stroke="none"
              fill={CHART_COLORS.train}
              fillOpacity={0.1}
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
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
            >
              <ErrorBar
                dataKey="trainErr"
                width={4}
                strokeWidth={1}
                stroke={CHART_COLORS.train}
                direction="y"
              />
            </Line>
            <Line
              dataKey="trainPowK"
              stroke={CHART_COLORS.train}
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={{ r: 2 }}
              isAnimationActive={false}
              name="train pass^k"
              connectNulls
            >
              <ErrorBar
                dataKey="trainPowKErr"
                width={4}
                strokeWidth={1}
                stroke={CHART_COLORS.train}
                direction="y"
              />
            </Line>
            <Area
              dataKey="holdoutBandLow"
              stackId="holdoutBand"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="holdoutBandHeight"
              stackId="holdoutBand"
              stroke="none"
              fill={CHART_COLORS.holdout}
              fillOpacity={0.15}
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="holdoutPowKBandLow"
              stackId="holdoutPowKBand"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
              connectNulls
            />
            <Area
              dataKey="holdoutPowKBandHeight"
              stackId="holdoutPowKBand"
              stroke="none"
              fill={CHART_COLORS.holdout}
              fillOpacity={0.1}
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
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
            >
              <ErrorBar
                dataKey="holdoutErr"
                width={4}
                strokeWidth={1}
                stroke={CHART_COLORS.holdout}
                direction="y"
              />
            </Line>
            <Line
              dataKey="holdoutPowK"
              stroke={CHART_COLORS.holdout}
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={{ r: 2 }}
              isAnimationActive={false}
              name="holdout pass^k"
              connectNulls
            >
              <ErrorBar
                dataKey="holdoutPowKErr"
                width={4}
                strokeWidth={1}
                stroke={CHART_COLORS.holdout}
                direction="y"
              />
            </Line>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {markers.length > 0 ? <MarkerLegend markers={markers} onJumpToFix={onJumpToFix} /> : null}
    </div>
  );
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

function trialSummary(pass1: RatePoint[], passK: RatePoint[]): string {
  const points = [...pass1, ...passK];
  const versions = Array.from(new Set(points.map((p) => p.version))).sort((a, b) => a - b);
  const countsByVersion = new Map<number, Set<number>>();
  let hasUnknown = false;

  for (const point of points) {
    const counts = countsByVersion.get(point.version) ?? new Set<number>();
    if (
      typeof point.trials === "number" &&
      Number.isFinite(point.trials) &&
      point.trials > 0
    ) {
      counts.add(point.trials);
    } else {
      hasUnknown = true;
    }
    countsByVersion.set(point.version, counts);
  }

  const allCounts = new Set(Array.from(countsByVersion.values()).flatMap((counts) => [...counts]));
  if (!hasUnknown && allCounts.size === 1) {
    return `trials = ${[...allCounts][0]}`;
  }
  if (versions.length === 0) return "trials = —";

  return `trials by version = ${versions
    .map((version) => {
      const counts = [...(countsByVersion.get(version) ?? [])].sort((a, b) => a - b);
      return `v${version}: ${counts.length > 0 ? counts.join("/") : "—"}`;
    })
    .join(", ")}`;
}

function bandFields(
  mean: number | undefined,
  std: number | undefined,
): { low: number | undefined; height: number | undefined } {
  if (mean === undefined || std === undefined) return { low: undefined, height: undefined };
  const low = clamp01(mean - std);
  const high = clamp01(mean + std);
  return { low, height: high - low };
}

function errFields(
  mean: number | undefined,
  min: number | undefined,
  max: number | undefined,
): [number, number] | undefined {
  if (mean === undefined || min === undefined || max === undefined) return undefined;
  return [Math.max(0, mean - min), Math.max(0, max - mean)];
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
    const trainBand = bandFields(train1?.mean, train1?.std);
    const holdoutBand = bandFields(holdout1?.mean, holdout1?.std);
    const trainPowKBand = bandFields(trainK?.mean, trainK?.std);
    const holdoutPowKBand = bandFields(holdoutK?.mean, holdoutK?.std);
    return {
      version,
      trainMean: train1?.mean,
      trainErr: errFields(train1?.mean, train1?.min, train1?.max),
      trainBandLow: trainBand.low,
      trainBandHeight: trainBand.height,
      trainPowK: trainK?.mean,
      trainPowKErr: errFields(trainK?.mean, trainK?.min, trainK?.max),
      trainPowKBandLow: trainPowKBand.low,
      trainPowKBandHeight: trainPowKBand.height,
      holdoutMean: holdout1?.mean,
      holdoutErr: errFields(holdout1?.mean, holdout1?.min, holdout1?.max),
      holdoutBandLow: holdoutBand.low,
      holdoutBandHeight: holdoutBand.height,
      holdoutPowK: holdoutK?.mean,
      holdoutPowKErr: errFields(holdoutK?.mean, holdoutK?.min, holdoutK?.max),
      holdoutPowKBandLow: holdoutPowKBand.low,
      holdoutPowKBandHeight: holdoutPowKBand.height,
    };
  });
}

function groupByVersion(markers: Marker[]): Map<number, Marker[]> {
  const out = new Map<number, Marker[]>();
  for (const m of markers) {
    const arr = out.get(m.version) ?? [];
    arr.push(m);
    out.set(m.version, arr);
  }
  return new Map([...out.entries()].sort((a, b) => a[0] - b[0]));
}

function lineColorFor(ms: Marker[]): string {
  for (const kind of LINE_PRIORITY) {
    if (ms.some((m) => m.kind === kind)) return MARKER_LINE_COLOR[kind];
  }
  return CHART_COLORS.mute;
}

function markerTitle(m: Marker): string {
  switch (m.kind) {
    case "fix_accepted":
    case "fix_rejected":
      return `lever: ${m.lever ?? "unknown"} — ${m.hypothesis ?? m.diagnosis ?? "no hypothesis recorded"}`;
    case "issue_opened":
      return `${m.source ?? "issue"} issue: ${m.title ?? m.issue_id ?? ""}`;
    case "memory_demoted":
      return `entry ${m.entry_id ?? "?"} demoted (${m.hits ?? 0} hits / ${m.misses ?? 0} misses)`;
    case "drift_cluster": {
      const byKind = Object.entries(m.count_by_kind ?? {})
        .map(([kind, count]) => `${kind}×${count}`)
        .join(", ");
      return `${m.count ?? 0} drift event${m.count === 1 ? "" : "s"}${byKind ? `: ${byKind}` : ""}`;
    }
    default:
      return m.kind;
  }
}

/**
 * The actual hover (native `title`) and click-through surface for markers:
 * Recharts gives no reliable way to attach interactive hover/click state to
 * an SVG annotation this deep in a composed chart, so the vertical
 * `ReferenceLine`s above are the visual marker and this chip strip — aligned
 * with them by version — is where hovering reads the lever/hypothesis and
 * clicking a fix chip jumps to its card.
 */
function MarkerLegend({
  markers,
  onJumpToFix,
}: {
  markers: Marker[];
  onJumpToFix?: (toVersion: number) => void;
}) {
  const sorted = [...markers].sort((a, b) => a.version - b.version || a.ts.localeCompare(b.ts));
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {sorted.map((m, i) => {
        const clickable =
          (m.kind === "fix_accepted" || m.kind === "fix_rejected") && m.to_version !== undefined;
        return (
          <button
            key={`${m.kind}-${m.version}-${i}`}
            type="button"
            title={markerTitle(m)}
            disabled={!clickable}
            onClick={() => clickable && onJumpToFix?.(m.to_version!)}
            className={clickable ? "cursor-pointer" : "cursor-default"}
          >
            <Pill tone={MARKER_TONE[m.kind]}>
              v{m.version} {MARKER_LABEL[m.kind]}
            </Pill>
          </button>
        );
      })}
    </div>
  );
}
