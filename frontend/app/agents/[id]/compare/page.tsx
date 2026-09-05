import { EmptyState, PageHeader } from "@/components/Page";

export default async function ComparePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <PageHeader
        title="Compare"
        subtitle={`GET /agents/${id}/compare?case_id=`}
      />
      <EmptyState>
        Side-by-side output for one case at v0 and at the current version, with
        the memory entries injected in each and the tool-call count. Pick a case
        once the agent has been run at two versions.
      </EmptyState>
    </>
  );
}
