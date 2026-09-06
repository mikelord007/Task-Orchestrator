"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { USE_MOCKS } from "@/lib/api";

const LINKS = [
  { href: "/agents", label: "agents" },
  { href: "/issues", label: "issues", unavailable: true },
  { href: "/insights", label: "insights" },
];

export default function Nav() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="sticky top-0 flex h-screen w-[172px] shrink-0 flex-col border-r border-line bg-ink-900 px-4 py-4">
      <Link href="/agents" className="block leading-tight">
        <span className="block text-[13px] text-fg">task</span>
        <span className="block text-[13px] text-fg-mute">orchestrator</span>
      </Link>

      <ul className="mt-7 space-y-px">
        {LINKS.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);

          if (link.unavailable) {
            return (
              <li key={link.href}>
                <button
                  type="button"
                  disabled
                  title="Issue tracking is unavailable in this build"
                  className="block w-full cursor-not-allowed border-l-2 border-transparent py-1 pl-2.5 text-left text-[12px] text-fg-mute opacity-60"
                >
                  <span className="block">{link.label}</span>
                  <span className="block text-[9px]">unavailable in this build</span>
                </button>
              </li>
            );
          }

          return (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`block border-l-2 py-1 pl-2.5 text-[12px] ${
                  active
                    ? "border-train bg-ink-800 text-fg"
                    : "border-transparent text-fg-mute hover:border-ink-600 hover:text-fg-dim"
                }`}
              >
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto space-y-2 text-[10px] leading-4 text-fg-mute">
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
