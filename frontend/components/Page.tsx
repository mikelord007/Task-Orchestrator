/** Shared chrome for the placeholder routes. W5 replaces the page bodies. */

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="mt-1 font-mono text-xs text-[var(--muted)]">
            {subtitle}
          </p>
        )}
      </div>
      {actions}
    </div>
  );
}

/**
 * Empty states must say what action produces data -- never a placeholder
 * number (PLAN.md §2.4).
 */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded border border-dashed border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center text-[var(--muted)]">
      {children}
    </div>
  );
}

export function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-[var(--border)] bg-[var(--surface)]">
      <h2 className="border-b border-[var(--border)] px-4 py-2 font-mono text-xs uppercase tracking-wide text-[var(--muted)]">
        {title}
      </h2>
      <div className="px-4 py-4">{children}</div>
    </section>
  );
}
