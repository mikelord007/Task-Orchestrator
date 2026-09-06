"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { USE_MOCKS } from "@/lib/api";

const LINKS = [
  { href: "/agents", label: "Agents", icon: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" },
  { href: "/issues", label: "Issues", unavailable: true, icon: "M12 8v5m0 3h.01M5 3h14v18H5z" },
  { href: "/insights", label: "Insights", icon: "M4 4v16h16M8 15v-4m5 4V7m5 8V3" },
];

export default function Nav() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="sticky top-0 flex h-screen w-[68px] shrink-0 flex-col border-r border-line bg-ink-800/50 px-2 py-6 md:w-[216px] md:px-4">
      <Link
        href="/agents"
        aria-label="Task Orchestrator"
        className="flex items-center gap-3 rounded-lg px-1 md:px-2"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-fg-mute/40 bg-ink-700 text-fg">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="h-6 w-6"
          >
            <path d="M9 3h6v6H9zM3 15h6v6H3zM15 15h6v6h-6zM12 9v3M6 15v-3h12v3" />
          </svg>
        </span>
        <span className="hidden leading-tight md:block">
          <span className="block font-sans text-base font-medium text-fg">Task</span>
          <span className="mt-0.5 block text-[11px] text-fg-dim">Orchestrator</span>
        </span>
      </Link>

      <p className="mb-3 mt-10 hidden px-3 text-[9px] uppercase tracking-[0.16em] text-fg-mute md:block">
        Workspace
      </p>
      <ul className="mt-8 space-y-2 md:mt-0">
        {LINKS.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);

          if (link.unavailable) {
            return (
              <li key={link.href}>
                <button
                  type="button"
                  disabled
                  title="Issue tracking is unavailable in this build"
                  aria-label={link.label}
                  className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg border border-transparent px-3 py-3 text-left text-[12px] text-fg-mute opacity-60"
                >
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className="h-4 w-4 shrink-0"
                  >
                    <path d={link.icon} />
                  </svg>
                  <span className="hidden md:block">
                    <span className="block">{link.label}</span>
                    <span className="mt-1 block text-[9px]">unavailable in this build</span>
                  </span>
                </button>
              </li>
            );
          }

          return (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-label={link.label}
                title={link.label}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg border px-3 py-3 text-[12px] transition-colors ${
                  active
                    ? "border-fg-mute/30 bg-ink-600 font-medium text-fg shadow-[inset_2px_0_0_var(--color-fg)]"
                    : "border-transparent text-fg-dim hover:border-line hover:bg-ink-700/60 hover:text-fg"
                }`}
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="h-4 w-4 shrink-0"
                >
                  <path d={link.icon} />
                </svg>
                <span className="hidden md:inline">{link.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto hidden space-y-3 border-t border-line pt-5 text-[10px] leading-5 text-fg-mute md:block">
        <p>
          Every number on these pages is a query over the append-only event ledger. Nothing is
          stored as a status.
        </p>
        {USE_MOCKS ? (
          <p className="rounded-xs border border-drift/40 px-1.5 py-1 text-drift">
            mock data. Unset NEXT_PUBLIC_USE_MOCKS to read the live backend.
          </p>
        ) : null}
      </div>
    </nav>
  );
}
