import Link from "next/link";
import type { ReactNode } from "react";
import type { DriftKind, Lever } from "@/lib/types";

/** A titled region. A hairline and a label, not a card. */
export function Panel({
  title,
  meta,
  actions,
  children,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-t border-line ${className}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2 py-2">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[13px] text-fg">{title}</h2>
          {meta ? <span className="text-[11px] text-fg-mute">{meta}</span> : null}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

/**
 * Empty states name the action that produces the data. Nothing here says
 * "nothing to see" without saying what to press.
 */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="border-l-2 border-ink-600 py-3 pl-3 text-[12px] text-fg-dim">{children}</p>
  );
}

export function Pill({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "pass" | "fail" | "train" | "holdout" | "drift" | "quiet";
  title?: string;
}) {
  const cls = {
    neutral: "border-line text-fg-dim",
    quiet: "border-ink-600 text-fg-mute",
    pass: "border-pass/40 text-pass",
    fail: "border-fail/40 text-fail",
    train: "border-train/40 text-train",
    holdout: "border-holdout/40 text-holdout",
    drift: "border-drift/40 text-drift",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-block rounded-xs border px-1.5 py-px text-[10px] leading-4 ${cls}`}
    >
      {children}
    </span>
  );
}

export function LeverChip({ lever }: { lever: Lever }) {
  return (
    <span
      className="inline-block rounded-xs bg-ink-700 px-1.5 py-px text-[10px] leading-4 text-fg-dim"
      title={`Lever: ${lever}`}
    >
      {lever}
    </span>
  );
}

export function DriftBadge({ kind }: { kind: DriftKind }) {
  return (
    <Pill tone="drift" title={`Drift watchdog fired on at least one trial: ${kind}`}>
      drift:{kind}
    </Pill>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
}) {
  const base =
    "rounded-xs border px-2.5 py-1 text-[12px] leading-5 disabled:cursor-not-allowed disabled:opacity-40";
  const cls =
    variant === "primary"
      ? "border-train/50 text-train hover:bg-train/10"
      : "border-line text-fg-dim hover:border-fg-mute hover:text-fg";
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={`${base} ${cls}`}>
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] text-fg-mute">{label}</span>
      {children}
      {hint ? <span className="mt-0.5 block text-[10px] text-fg-mute">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "mt-1 w-full rounded-xs border border-line bg-ink-800 px-2 py-1.5 text-[12px] text-fg placeholder:text-fg-mute focus:border-train focus:outline-none";

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-3">
      <div className="min-w-0">
        <h1 className="text-[15px] text-fg">{title}</h1>
        {subtitle ? <div className="mt-1 text-[12px] text-fg-dim">{subtitle}</div> : null}
      </div>
      {right}
    </div>
  );
}

export function Crumb({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="text-fg-mute hover:text-fg">
      {children}
    </Link>
  );
}

/** Table primitives: row hairlines only, no vertical rules, no zebra. */
export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <th className={`border-b border-line py-1.5 pr-4 text-left font-normal text-fg-mute ${className}`}>
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`border-b border-line-soft py-1.5 pr-4 align-top ${className}`}>{children}</td>;
}
