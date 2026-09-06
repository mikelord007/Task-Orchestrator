"use client";

import { Button, Empty, PageHeader, Panel } from "@/components/ui";

export default function IssuesPage() {
  return (
    <div className="mx-auto max-w-[1200px] px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
      <PageHeader
        title="Issues"
        subtitle="Issue tracking was not included in this build. No issue data is loaded or submitted."
        right={
          <Button
            variant="primary"
            disabled
            title="Issue tracking is unavailable in this build"
          >
            New issue · unavailable in this build
          </Button>
        }
      />

      <Panel title="Unavailable" className="mt-5">
        <Empty>
          The issue workflow was deliberately cut from this build, so this page does not call an
          issues backend.
        </Empty>
      </Panel>
    </div>
  );
}
