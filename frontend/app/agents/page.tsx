import { EmptyState, PageHeader } from "@/components/Page";

export default function AgentsPage() {
  return (
    <>
      <PageHeader
        title="Agents"
        subtitle="GET /agents"
        actions={
          <button
            type="button"
            disabled
            className="rounded border border-[var(--border)] px-3 py-1.5 text-[var(--muted)]"
          >
            New agent
          </button>
        }
      />
      <EmptyState>
        No agents yet. W5 builds the list and the new-agent form
        (goal, domain, tools, evaluator, use_playbook) against{" "}
        <code className="font-mono">POST /agents</code>.
      </EmptyState>
    </>
  );
}
