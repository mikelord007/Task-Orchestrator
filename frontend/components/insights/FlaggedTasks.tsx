import type { FlaggedTask } from "@/lib/types";
import { Empty, Pill } from "@/components/ui";

/**
 * Tasks at 0% across the last 3 versions. Per the evals post: this is usually
 * a broken task, not an incapable agent — so it is surfaced for review, not
 * silently counted against the agent.
 */
export default function FlaggedTasks({ tasks }: { tasks: FlaggedTask[] }) {
  if (tasks.length === 0) {
    return (
      <Empty>
        None. A task flags here only after 3 versions of train history with it stuck at 0%.
      </Empty>
    );
  }

  return (
    <ul className="space-y-1.5">
      {tasks.map((t) => (
        <li key={t.case_id} className="flex flex-wrap items-center gap-2 text-[12px]">
          <Pill tone="fail">{t.case_id}</Pill>
          <span className="text-fg-mute">
            0% at v{t.versions_at_zero.join(", v")}
          </span>
          {t.tag ? <span className="text-fg-mute">({t.tag})</span> : null}
        </li>
      ))}
    </ul>
  );
}
