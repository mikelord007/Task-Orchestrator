import type { RateStat } from "@/lib/types";
import { DASH, pct } from "@/lib/format";

/**
 * The uncertainty rail: a value, its spread, and a band showing min to max.
 * Every headline number in this product is a measurement, so none of them is
 * allowed to appear without its error. A null value reads as a dash, never 0.
 */
export default function Stat({
  label,
  rate,
  value,
  suffix,
  tone = "neutral",
  size = "md",
}: {
  label: string;
  /** Pass a rate to get the mean ± std readout and the min/max band. */
  rate?: RateStat | null;
  /** Or pass a preformatted value for non-rate stats. */
  value?: string;
  suffix?: string;
  tone?: "neutral" | "train" | "holdout" | "pass" | "fail" | "drift";
  size?: "sm" | "md" | "lg";
}) {
  const toneClass = {
    neutral: "text-fg",
    train: "text-train",
    holdout: "text-holdout",
    pass: "text-pass",
    fail: "text-fail",
    drift: "text-drift",
  }[tone];

  const bandColor = {
    neutral: "bg-fg-mute",
    train: "bg-train",
    holdout: "bg-holdout",
    pass: "bg-pass",
    fail: "bg-fail",
    drift: "bg-drift",
  }[tone];

  const valueSize = { sm: "text-xl", md: "text-3xl", lg: "text-4xl" }[size];

  const hasRate = rate !== undefined && rate !== null;
  const shown = hasRate ? pct(rate.mean) : (value ?? DASH);
  const isEmpty = shown === DASH;

  return (
    <div className="min-w-[112px] border-t-2 border-line-soft pt-3">
      <div className="flex flex-wrap items-baseline gap-1.5">
        <span
          className={`border border-dashed border-fg-mute bg-ink-600 px-2 py-0.5 font-mono font-bold tabular-nums leading-tight ${valueSize} ${isEmpty ? "text-fg-mute" : toneClass}`}
        >
          {shown}
        </span>
        {!isEmpty && suffix ? (
          <span className="text-[11px] text-fg-mute">{suffix}</span>
        ) : null}
        {hasRate && !isEmpty ? (
          <span className="text-[11px] tabular-nums text-fg-dim">± {pct(rate.std)}</span>
        ) : null}
      </div>
      <div className="mt-2 font-mono text-[10px] font-medium uppercase tracking-[0.06em] leading-4 text-fg-mute">{label}</div>
      {hasRate && !isEmpty ? <Band rate={rate} color={bandColor} /> : null}
    </div>
  );
}

/** min -> max drawn against the full 0-100 range. */
function Band({ rate, color }: { rate: RateStat; color: string }) {
  const left = Math.max(0, Math.min(100, rate.min * 100));
  const width = Math.max(1.5, Math.min(100 - left, (rate.max - rate.min) * 100));
  return (
    <div
      className="relative mt-2 h-[3px] w-full bg-ink-600"
      title={`min ${pct(rate.min)} / max ${pct(rate.max)} over trials`}
    >
      <div
        className={`absolute top-0 h-[3px] ${color} opacity-70`}
        style={{ left: `${left}%`, width: `${width}%` }}
      />
      <div
        className={`absolute top-[-1px] h-[5px] w-px ${color}`}
        style={{ left: `${Math.min(99.7, rate.mean * 100)}%` }}
      />
    </div>
  );
}
