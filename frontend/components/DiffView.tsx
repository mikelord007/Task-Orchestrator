"use client";

import { useEffect, useState } from "react";
import { getFixDiff } from "@/lib/api";

function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-fg-mute";
  if (line.startsWith("@@")) return "text-holdout";
  if (line.startsWith("+")) return "bg-pass/10 text-pass";
  if (line.startsWith("-")) return "bg-fail/10 text-fail";
  return "text-fg-dim";
}

/** Unified diff, fetched on expand so a long timeline stays cheap. */
export default function DiffView({
  agentId,
  toVersion,
}: {
  agentId: string;
  toVersion: number;
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getFixDiff(agentId, toVersion)
      .then((t) => !cancelled && setText(t))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [agentId, toVersion]);

  if (error) return <p className="py-2 text-[11px] text-fail">Diff unavailable: {error}</p>;
  if (text === null) return <p className="py-2 text-[11px] text-fg-mute">Loading diff…</p>;

  return (
    <pre className="mt-2 max-h-96 overflow-auto border border-line bg-ink-800 p-2 text-[11px] leading-[1.45]">
      {text.split("\n").map((line, i) => (
        <div key={i} className={`whitespace-pre ${lineClass(line)}`}>
          {line === "" ? " " : line}
        </div>
      ))}
    </pre>
  );
}
