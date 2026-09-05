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
        None. A task flags here only after 3 versions of train history with it stuck at 0%.
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
