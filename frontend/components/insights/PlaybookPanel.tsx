import type { Lesson } from "@/lib/types";
import { Empty, LeverChip } from "@/components/ui";

/** Lessons distilled from accepted fixes, linked back to the agent (and issue) that produced them. */
export default function PlaybookPanel({ lessons }: { lessons: Lesson[] }) {
  if (lessons.length === 0) {
    return (
      <Empty>
        No lessons yet. One is distilled from each accepted fix; they carry over to the next agent
        you generate with the playbook toggle on.
      </Empty>
    );
  }

  return (
    <ul className="space-y-3">
      {lessons.map((lesson) => (
        <li key={lesson.id} className="border-b border-line-soft pb-3 last:border-b-0">
          <div className="flex flex-wrap items-center gap-2">
            <LeverChip lever={lesson.lever} />
            <span className="text-[11px] text-fg-mute">{lesson.domain_tags.join(", ")}</span>
            <span className="text-[11px] text-fg-mute">from {lesson.source_agent_id}</span>
            {lesson.source_issue_id ? (
              <span className="text-[11px] text-fg-mute">via {lesson.source_issue_id}</span>
            ) : null}
          </div>
          <p className="mt-1 text-[11px] text-fg-mute">when: {lesson.trigger}</p>
          <p className="prose-h mt-0.5 text-fg">{lesson.lesson}</p>
        </li>
      ))}
    </ul>
  );
}
