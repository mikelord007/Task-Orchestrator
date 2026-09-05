"use client";

import type { JobHandle } from "@/lib/useJob";

/** Progress readout for the job started by Run train / Run holdout / Improve. */
export default function JobBar({ handle }: { handle: JobHandle }) {
  const { job, label, error } = handle;
  if (!job && !error) return null;

  if (error) {
    return (
      <div className="border-t border-fail/40 py-2 text-[12px] text-fail">
        {label ? `${label}: ` : ""}
        {error}
      </div>
    );
  }
  if (!job) return null;

  const { done, total } = job.progress;
  const fraction = total > 0 ? done / total : 0;
  const finished = job.status === "done";

  return (
    <div className="border-t border-line py-2">
      <div className="flex items-baseline justify-between gap-3 text-[11px]">
        <span className={finished ? "text-pass" : "text-fg-dim"}>
          {label ?? job.kind} — {job.status}
        </span>
        <span className="tabular-nums text-fg-mute">
          {done} / {total}
        </span>
      </div>
      <div className="mt-1 h-[3px] w-full bg-ink-700">
        <div
          className={`h-[3px] ${finished ? "bg-pass" : "bg-train"}`}
          style={{ width: `${Math.round(fraction * 100)}%`, transition: "width 300ms linear" }}
        />
      </div>
      {finished ? (
        <button
          onClick={handle.clear}
          className="mt-1 text-[10px] text-fg-mute underline-offset-2 hover:text-fg-dim hover:underline"
        >
          dismiss
        </button>
      ) : null}
    </div>
  );
}
