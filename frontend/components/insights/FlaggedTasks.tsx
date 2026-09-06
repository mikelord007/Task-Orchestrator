import { Empty, Pill } from "@/components/ui";

/**
 * Tasks at 0% across the last 3 versions. Per the evals post: this is usually
 * a broken task, not an incapable agent — so it is surfaced for review, not
 * silently counted against the agent.
 */
export default function FlaggedTasks({ tasks }: { tasks: string[] }) {
  if (tasks.length === 0) {
    return (
      <Empty>
        No task has enough failing history yet. Run the train split across 3 versions; tasks still
        at 0% then flag here for review.
      </Empty>
    );
  }

  return (
    <ul className="flex flex-wrap gap-1.5">
      {tasks.map((caseId) => (
        <li key={caseId}>
          <Pill tone="fail">{caseId}</Pill>
        </li>
      ))}
    </ul>
  );
}
