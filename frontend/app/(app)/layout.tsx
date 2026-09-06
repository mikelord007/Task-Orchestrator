import Nav from "@/components/Nav";

/** Keep dashboard navigation separate from the public landing page. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Nav />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
