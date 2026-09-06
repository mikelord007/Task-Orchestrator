import Link from "next/link";
import type { ReactNode } from "react";
import type { DriftKind, Lever } from "@/lib/types";

/** A titled card with a consistent header and padded content. */
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
    <section
      className={`min-w-0 rounded-xl border border-line bg-ink-800/60 shadow-sm shadow-ink-900/30 ${className}`}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line-soft px-5 py-4">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <h2 className="text-[13px] font-medium text-fg">{title}</h2>
          {meta ? <span className="text-[11px] text-fg-mute">{meta}</span> : null}
        </div>
        {actions}
      </header>
      <div className="min-w-0 overflow-x-auto p-4 sm:p-5">{children}</div>
    </section>
  );
}

/**
 * Empty states name the action that produces the data. Nothing here says
 * "nothing to see" without saying what to press.
 */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-dashed border-line bg-ink-900/40 px-4 py-6">
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="mt-0.5 h-5 w-5 shrink-0 text-fg-mute"
      >
        <path d="M4 7h16v13H4zM8 4h8M8 11h8M8 15h5" />
      </svg>
      <p className="min-w-0 max-w-[72ch] break-words text-[12px] leading-6 text-fg-dim">{children}</p>
    </div>
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
    neutral: "border-line bg-ink-700 text-fg-dim",
    quiet: "border-line bg-ink-900/50 text-fg-dim",
    pass: "border-pass/25 bg-pass/10 text-pass",
    fail: "border-fail/25 bg-fail/10 text-fail",
    train: "border-train/25 bg-train/10 text-train",
    holdout: "border-holdout/25 bg-holdout/10 text-holdout",
    drift: "border-drift/25 bg-drift/10 text-drift",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] leading-4 ${cls}`}
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
    "inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-[12px] font-medium leading-5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40";
  const cls =
    variant === "primary"
      ? "border-fg bg-fg text-ink-900 shadow-sm enabled:hover:border-fg-dim enabled:hover:bg-fg-dim"
      : "border-line bg-ink-800 text-fg-dim enabled:hover:border-fg-mute enabled:hover:bg-ink-700 enabled:hover:text-fg";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${base} ${cls}`}
    >
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
      <span className="block text-[11px] font-medium text-fg-dim">{label}</span>
      {children}
      {hint ? <span className="mt-2 block text-[11px] leading-5 text-fg-mute">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "mt-2 w-full min-w-0 rounded-lg border border-line bg-ink-900 px-3 py-2.5 text-[12px] leading-5 text-fg placeholder:text-fg-mute transition-colors hover:border-fg-mute/50 focus:border-fg-dim focus:outline-none focus:ring-2 focus:ring-fg/10";

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
    <div className="flex flex-wrap items-start justify-between gap-5 border-b border-line pb-6">
      <div className="min-w-0">
        <h1 className="font-sans text-3xl font-medium tracking-tight text-fg">{title}</h1>
        {subtitle ? (
          <div className="mt-2 max-w-[72ch] font-sans text-[14px] leading-6 text-fg-dim">
            {subtitle}
          </div>
        ) : null}
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
    <th
      className={`border-b border-line py-1.5 pr-4 text-left font-normal text-fg-mute ${className}`}
    >
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <td className={`border-b border-line-soft py-1.5 pr-4 align-top ${className}`}>{children}</td>
  );
}
