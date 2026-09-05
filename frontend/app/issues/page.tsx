import { EmptyState, PageHeader } from "@/components/Page";

export default function IssuesPage() {
  return (
    <>
      <PageHeader
        title="Issues"
        subtitle="GET /issues"
        actions={
          <button
            type="button"
            disabled
            className="rounded border border-[var(--border)] px-3 py-1.5 text-[var(--muted)]"
          >
            New issue
          </button>
        }
      />
      <EmptyState>
        No issues yet. File one against an agent to turn a human report into a
        regression case.
      </EmptyState>
    </>
  );
}
