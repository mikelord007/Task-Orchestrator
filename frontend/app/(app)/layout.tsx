import Nav from "@/components/Nav";

/** Keep dashboard navigation separate from the public landing page. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-ink-800 md:flex-row">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-fg focus:p-3 focus:text-ink-900">Skip to content</a>
      <Nav />
      <main id="main" className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
