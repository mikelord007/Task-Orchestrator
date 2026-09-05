import Link from "next/link";
import { EmptyState, PageHeader } from "@/components/Page";

export default async function AgentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <PageHeader title={`Agent ${id}`} subtitle={`GET /agents/${id}`} />
      <nav className="mb-6 flex gap-4 border-b border-[var(--border)] pb-2 text-[var(--muted)]">
        {["Prompt", "Tools", "Memory", "Runs", "Fixes"].map((tab) => (
          <span key={tab}>{tab}</span>
        ))}
        <Link
          href={`/agents/${id}/compare`}
          className="ml-auto text-[var(--accent)]"
        >
          Compare v0 &rarr; current
        </Link>
      </nav>
      <EmptyState>
        W5 builds the tabs, the per-repeat case table and the fix-card timeline
        here. Run the agent to produce data.
      </EmptyState>
    </>
  );
}
