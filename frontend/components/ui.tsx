import Link from "next/link";
import type { ReactNode } from "react";
import type { DriftKind, Lever } from "@/lib/types";

/** Architectural panel: square surface, ruled header, and flush-left content. */
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
      className={`min-w-0 border border-line-soft bg-ink-700 ${className}`}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-line-soft px-5 py-4 sm:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <h2 className="font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-fg">{title}</h2>
          {meta ? <span className="font-mono text-[10px] text-fg-mute">{meta}</span> : null}
        </div>
        {actions}
      </header>
      <div className="min-w-0 overflow-x-auto p-5 sm:p-6">{children}</div>
    </section>
  );
}

/**
 * Empty states name the action that produces the data. Nothing here says
 * "nothing to see" without saying what to press.
 */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="border border-dashed border-fg-mute bg-ink-600 px-4 py-6">
      <p className="small-label mb-3">No recorded value</p>
      <p className="min-w-0 max-w-[72ch] break-words text-[13px] leading-6 text-fg-dim">{children}</p>
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
    neutral: "border-line bg-ink-600 text-fg-dim",
    quiet: "border-line bg-ink-800 text-fg-dim",
    pass: "border-fg bg-fg text-ink-900",
    fail: "border-fail bg-fail text-ink-900",
    train: "border-fg bg-fg text-ink-900",
    holdout: "border-fg-mute bg-fg-mute text-ink-900",
    drift: "border-drift bg-drift text-ink-900",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex items-center border px-[11px] py-[7px] font-mono text-[11px] font-bold uppercase leading-4 tracking-[0.06em] ${cls}`}
    >
      {children}
    </span>
  );
}

export function LeverChip({ lever }: { lever: Lever }) {
  return (
    <span
      className="inline-block border border-dashed border-fg-mute bg-ink-600 px-2 py-0.5 font-mono text-[10px] leading-4 text-fg-dim"
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
    "inline-flex items-center justify-start gap-3 border px-4 py-2.5 font-mono text-[11px] font-bold uppercase tracking-[0.08em] leading-5 transition-colors disabled:cursor-not-allowed disabled:opacity-40";
  const cls =
    variant === "primary"
      ? "border-fg bg-fg text-ink-900 enabled:hover:border-[#ff9783] enabled:hover:bg-[#ff9783]"
      : "border-line bg-ink-700 text-fg-dim enabled:hover:border-[#ff9783] enabled:hover:text-[#ff9783]";
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
      <span className="small-label block">{label}</span>
      {children}
      {hint ? <span className="mt-2 block text-[11px] leading-5 text-fg-mute">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "mt-2 w-full min-w-0 border border-line bg-ink-600 px-3 py-2.5 font-mono text-[12px] leading-5 text-fg placeholder:text-fg-mute transition-colors hover:border-fg-mute focus:border-fg focus:outline-none";

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
    <div className="flex flex-wrap items-start justify-between gap-6 border-b-2 border-line-soft pb-6">
      <div className="min-w-0">
        <p className="eyebrow mb-3">Control surface</p>
        <h1 className="display-type font-sans text-4xl text-fg sm:text-5xl">{title}</h1>
        {subtitle ? (
          <div className="mt-3 max-w-[72ch] font-sans text-[15px] leading-6 text-fg-body">
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
    <Link href={href} className="font-mono text-fg-mute hover:text-[#ff9783]">
      {children}
    </Link>
  );
}

/** Table primitives: row hairlines only, no vertical rules, no zebra. */
export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <th
      className={`border-b-2 border-line-soft py-2 pr-4 text-left font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-fg-mute ${className}`}
    >
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <td className={`border-b border-line-soft py-2.5 pr-4 align-top font-mono ${className}`}>{children}</td>
  );
}
