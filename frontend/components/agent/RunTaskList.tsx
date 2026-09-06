import Link from "next/link";
import PassStrip from "@/components/PassStrip";
import { DriftBadge } from "@/components/ui";
import { ms, num, usd } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

export default function RunTaskList({
  run,
  agentId,
  ruleText,
}: {
  run: RunSummary;
  agentId: string;
  ruleText: Record<string, string>;
}) {
  return (
    <div className="border-y border-line-soft">
      <div
        aria-hidden="true"
        className="hidden grid-cols-[minmax(0,1fr)_minmax(10rem,0.6fr)_5rem] gap-8 border-b border-line-soft px-1 py-3 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-fg-mute sm:grid"
      >
        <span>task</span>
        <span>trials</span>
        <span className="text-right">score</span>
      </div>

      <div className="divide-y divide-line-soft">
        {run.tasks.map((task) => (
          <article key={task.case_id} className="px-1 py-5 sm:py-6">
            <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_minmax(10rem,0.6fr)_5rem] sm:items-center sm:gap-8">
              <div className="min-w-0">
                <span className="mb-1 block font-mono text-[9px] uppercase tracking-[0.08em] text-fg-mute sm:hidden">
                  task
                </span>
                <Link
                  href={`/agents/${agentId}/compare?case_id=${encodeURIComponent(task.case_id)}`}
                  className="break-words font-mono text-[12px] leading-5 text-fg hover:text-[#ff9783] hover:underline"
                  title="Compare v0 and the current version on this task"
                >
                  {task.case_id}
                </Link>
              </div>

              <div>
                <span className="mb-2 block font-mono text-[9px] uppercase tracking-[0.08em] text-fg-mute sm:hidden">
                  trials
                </span>
                <PassStrip passed={task.passed_by_trial} />
              </div>

              <div className="sm:text-right">
                <span className="mb-1 block font-mono text-[9px] uppercase tracking-[0.08em] text-fg-mute sm:hidden">
                  score
                </span>
                <span className="font-mono text-[13px] tabular-nums text-fg-dim">
                  {num(task.score, 2)}
                </span>
              </div>
            </div>

            <details className="group mt-5 border-t border-line-soft pt-4">
              <summary className="flex cursor-pointer list-none items-center gap-3 font-mono text-[10px] font-bold uppercase tracking-[0.08em] text-fg-mute transition-colors hover:text-[#ff9783] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-fg [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="text-fg group-open:hidden">
                  +
                </span>
                <span aria-hidden="true" className="hidden text-fg group-open:inline">
                  −
                </span>
                execution details
              </summary>

              <dl className="mt-5 grid gap-x-8 gap-y-6 border-l border-line-soft pl-4 sm:grid-cols-2 sm:pl-6 lg:grid-cols-4">
                <Detail label="cost">{usd(task.cost_usd)}</Detail>
                <Detail label="latency">{ms(task.latency_ms)}</Detail>
                <Detail label="tool calls">
                  <span className="tabular-nums">{task.tool_calls}</span>
                </Detail>
                <Detail label="tool errors">
                  <span className={`tabular-nums ${task.tool_errors > 0 ? "text-fail" : "text-fg-dim"}`}>
                    {task.tool_errors}
                  </span>
                </Detail>

                <Detail label="injected rules" className="sm:col-span-2">
                  {task.rules_injected.length === 0 ? (
                    <span className="text-fg-mute">None</span>
                  ) : (
                    <ul className="space-y-2">
                      {task.rules_injected.map((id) => (
                        <li key={id} className="break-words">
                          <span className="text-fg">{id}</span>
                          <span className="text-fg-mute"> · </span>
                          {ruleText[id] ?? "Text not in this version"}
                        </li>
                      ))}
                    </ul>
                  )}
                </Detail>

                <Detail label="drift">
                  {task.drift_kind ? <DriftBadge kind={task.drift_kind} /> : <span className="text-fg-mute">None</span>}
                </Detail>

                <Detail label="artifacts">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    {task.trace_url ? (
                      <a
                        href={task.trace_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[#ff563c] hover:text-[#ff9783] hover:underline"
                      >
                        Open trace
                      </a>
                    ) : null}
                    {task.transcript_path ? (
                      <span className="text-fg-dim" title={task.transcript_path}>
                        Transcript recorded
                      </span>
                    ) : null}
                    {!task.trace_url && !task.transcript_path ? (
                      <span className="text-fg-mute">None</span>
                    ) : null}
                  </div>
                </Detail>
              </dl>
            </details>
          </article>
        ))}
      </div>
    </div>
  );
}

function Detail({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="mb-2 font-mono text-[9px] uppercase tracking-[0.08em] text-fg-mute">{label}</dt>
      <dd className="font-mono text-[11px] leading-5 text-fg-dim">{children}</dd>
    </div>
  );
}
