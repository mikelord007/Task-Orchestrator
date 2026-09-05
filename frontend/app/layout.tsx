import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { USE_MOCKS } from "@/lib/api";

export const metadata: Metadata = {
  title: "Task Orchestrator",
  description:
    "Generate, evaluate and improve specialized agents against an evaluator.",
};

const NAV = [
  { href: "/agents", label: "Agents" },
  { href: "/issues", label: "Issues" },
  { href: "/insights", label: "Insights" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <header className="border-b border-[var(--border)]">
          <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
            <Link
              href="/agents"
              className="font-mono text-sm font-semibold tracking-tight"
            >
              task-orchestrator
            </Link>
            <ul className="flex items-center gap-4">
              {NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
            {USE_MOCKS && (
              <span className="ml-auto rounded border border-[var(--border)] px-2 py-0.5 font-mono text-xs text-[var(--muted)]">
                mocks
              </span>
            )}
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
