import { EmptyState, PageHeader } from "@/components/Page";

export default async function IssueDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <PageHeader title={`Issue ${id}`} subtitle={`GET /issues/${id}`} />
      <EmptyState>
        W7 fills in the body, the linked cases and the fix timeline
        (proposed &rarr; accepted/rejected with lever and diagnosis).
      </EmptyState>
    </>
  );
}
