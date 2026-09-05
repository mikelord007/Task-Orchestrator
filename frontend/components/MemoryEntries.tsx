import type { MemoryEntryChange } from "@/lib/types";
import { Pill } from "./ui";

const CHANGE_TONE = {
  added: "pass",
  updated: "train",
  demoted: "drift",
} as const;

/**
 * The entries a lever=memory fix wrote or demoted. Shown in place of a text
 * diff, because a jsonl diff hides exactly the thing worth reading.
 */
export default function MemoryEntries({ entries }: { entries: MemoryEntryChange[] }) {
  return (
    <ul className="mt-2 space-y-2">
      {entries.map((entry) => (
        <li key={entry.id} className="border-l-2 border-ink-600 pl-3">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={CHANGE_TONE[entry.change ?? "added"]}>{entry.change ?? "added"}</Pill>
            <span className="text-[11px] text-fg-mute">{entry.kind.replace("_", " ")}</span>
            <span className="text-[11px] text-fg-mute">{entry.id}</span>
            {entry.tool ? <Pill tone="quiet">{entry.tool}</Pill> : null}
            {entry.confidence !== undefined ? (
              <span className="text-[11px] tabular-nums text-fg-mute">
                confidence {entry.confidence.toFixed(2)}
              </span>
            ) : null}
          </div>
          <p className="prose-h mt-1 text-fg">{entry.rule ?? entry.note ?? entry.text}</p>
          {entry.rule && entry.text ? (
            <p className="mt-0.5 text-[11px] text-fg-mute">{entry.text}</p>
          ) : null}
          {entry.evidence ? (
            <p className="prose-h mt-0.5 text-[12px] text-fg-dim">{entry.evidence}</p>
          ) : null}
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-mute">
            {entry.scope_keywords?.length ? (
              <span>scope: {entry.scope_keywords.join(", ")}</span>
            ) : null}
            {entry.evidence_case_ids?.length ? (
              <span>evidence: {entry.evidence_case_ids.join(", ")}</span>
            ) : null}
            {entry.source ? <span>source: {entry.source}</span> : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
