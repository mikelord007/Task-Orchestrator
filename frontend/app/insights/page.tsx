import { EmptyState, PageHeader, Panel } from "@/components/Page";

const CHARTS = [
  ["Pass rate by version", "mean with the min/max band over EVAL_REPEATS"],
  ["Memory growth", "rules + tool notes per version, demotions marked"],
  ["Tool efficiency", "tool calls, tool errors, tokens and latency per case"],
  ["Cost per run", "USD per run by version"],
  ["Drift", "detections by kind and tokens saved"],
];

export default function InsightsPage() {
  return (
    <>
      <PageHeader title="Insights" subtitle="GET /insights/{agent_id}" />
      <div className="grid gap-4 md:grid-cols-2">
        {CHARTS.map(([title, hint]) => (
          <Panel key={title} title={title}>
            <EmptyState>
              {hint}. Nothing to plot until a run writes to the ledger.
            </EmptyState>
          </Panel>
        ))}
      </div>
    </>
  );
}
