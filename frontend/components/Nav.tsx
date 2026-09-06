"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Brand from "@/components/Brand";
import { LIVE_MODEL_CALLS, USE_MOCKS } from "@/lib/api";

const LINKS = [
  { href: "/agents", index: "01", label: "Agents" },
  { href: "/issues", index: "02", label: "Issues", unavailable: true },
  { href: "/insights", index: "03", label: "Insights" },
];

export default function Nav() {
  const pathname = usePathname() ?? "";

  return (
    <nav className="sticky top-0 z-40 flex w-full shrink-0 flex-col border-b-2 border-line-soft bg-ink-900 md:h-screen md:w-[248px] md:border-b-0 md:border-r-2">
      <div className="flex items-center justify-between gap-5 border-b border-line-soft px-4 py-4 md:block md:px-6 md:py-6">
        <span className="md:hidden"><Brand compact href="/agents" /></span>
        <span className="hidden md:block"><Brand href="/agents" /></span>
        <p className="small-label hidden md:mt-10 md:block">Workspace / public demo</p>
        <ul className="flex gap-1 md:mt-4 md:grid md:gap-2">
          {LINKS.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href}>
                {link.unavailable ? (
                  <button
                    type="button"
                    disabled
                    title="Issue tracking is unavailable in this build"
                    aria-label={`${link.label}, unavailable`}
                    className="flex w-full cursor-not-allowed items-center gap-3 border border-transparent px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute opacity-55 md:py-3"
                  >
                    <span>{link.index}</span><span>{link.label}</span><span className="hidden text-[8px] md:ml-auto md:block">off</span>
                  </button>
                ) : (
                  <Link
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-3 border px-3 py-2.5 font-mono text-[10px] font-bold uppercase tracking-[0.06em] transition-colors md:py-3 ${
                      active
                        ? "border-fg bg-fg text-ink-900"
                        : "border-transparent text-fg-dim hover:border-[#ff9783] hover:text-[#ff9783]"
                    }`}
                  >
                    <span>{link.index}</span><span>{link.label}</span>
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="mt-auto hidden border-t-2 border-line-soft p-6 md:block">
        <p className="font-mono text-[10px] leading-5 text-fg-mute">Metrics are derived from the append-only event ledger.</p>
        <div className="mt-5 grid gap-2">
          <p className={`border px-2 py-2 font-mono text-[9px] font-bold uppercase tracking-[0.05em] ${USE_MOCKS ? "border-line bg-ink-600 text-fg-mute" : "border-fg bg-fg text-ink-900"}`}>
            {USE_MOCKS ? "Mock dataset" : "Live backend data"}
          </p>
          {!USE_MOCKS && !LIVE_MODEL_CALLS ? (
            <p className="border border-line bg-ink-600 px-2 py-2 font-mono text-[9px] font-bold uppercase tracking-[0.05em] text-fg-mute">Model actions unavailable</p>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
