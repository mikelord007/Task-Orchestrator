"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { compareCase, getAgent, listRuns } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import type { CompareSide, Json } from "@/lib/types";
import { compactTokens } from "@/lib/format";
import { Crumb, Empty, PageHeader, Pill } from "@/components/ui";

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="px-6 py-5 text-[12px] text-fg-mute">Loading…</div>}>
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const agentId = params.id;
  const caseId = search.get("case_id");

  const agent = useAsync(() => getAgent(agentId), [agentId]);
  const runs = useAsync(() => listRuns(agentId), [agentId]);
  const result = useAsync(
    () => (caseId ? compareCase(agentId, caseId) : Promise.resolve(null)),
    [agentId, caseId],
  );

  const cases = useMemo(() => {
    const seen = new Set<string>();
    for (const run of runs.data ?? []) for (const c of run.cases) seen.add(c.case_id);
    return Array.from(seen).sort();
  }, [runs.data]);

  function pick(id: string) {
    router.replace(`/agents/${agentId}/compare?case_id=${encodeURIComponent(id)}`, {
      scroll: false,
    });
  }

  const currentVersion = result.data?.current_version ?? agent.data?.current_version ?? 0;

  return (
    <div className="mx-auto max-w-[1360px] px-6 py-5">
      <div className="mb-2 text-[11px]">
        <Crumb href="/agents">agents</Crumb>
        <span className="text-fg-mute"> / </span>
        <Crumb href={`/agents/${agentId}`}>{agentId}</Crumb>
        <span className="text-fg-mute"> / compare</span>
      </div>

      <PageHeader
        title="Compare one case across versions"
        subtitle="The same input, graded against the same expected answer, at v0 and at the current version. Fields matching the expected answer are green, fields differing are red."
      />

      <div className="mt-3 border-b border-line pb-3">
        <div className="text-[11px] text-fg-mute">case</div>
        {runs.loading ? (
          <p className="text-[12px] text-fg-mute">Loading cases…</p>
        ) : cases.length === 0 ? (
          <Empty>
            No cases to compare. Run a split on this agent first; the picker lists every case that
            appears in a recorded run.
          </Empty>
        ) : (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {cases.map((id) => (
              <button
                key={id}
                onClick={() => pick(id)}
                aria-pressed={id === caseId}
                className={`rounded-xs border px-2 py-0.5 text-[11px] ${
                  id === caseId
                    ? "border-train/50 bg-train/10 text-train"
                    : "border-line text-fg-mute hover:border-fg-mute hover:text-fg-dim"
                }`}
              >
                {id}
              </button>
            ))}
          </div>
        )}
      </div>

      {!caseId ? (
        <Empty>Pick a case above. This page is deep-linkable as ?case_id=&lt;id&gt;.</Empty>
      ) : result.loading ? (
        <p className="py-4 text-[12px] text-fg-mute">Loading {caseId}…</p>
      ) : result.error ? (
        <Empty>Could not load {caseId}: {result.error}</Empty>
      ) : !result.data ? null : (
        <div className="grid gap-px bg-line pt-4 md:grid-cols-3">
          <Column
            title="expected"
            note="Ground truth from the evaluator."
            output={result.data.expected}
            expected={result.data.expected}
            side={null}
          />
          <Column
            title="v0"
            note="The generated agent, before any improvement."
            output={result.data.v0?.output ?? null}
            expected={result.data.expected}
            side={result.data.v0}
          />
          <Column
            title={`v${currentVersion}`}
            note="The current version."
            output={result.data.current?.output ?? null}
            expected={result.data.expected}
            side={result.data.current}
          />
        </div>
      )}
    </div>
  );
}

function Column({
  title,
  note,
  output,
  expected,
  side,
}: {
  title: string;
  note: string;
  output: Json | null;
  expected: Json;
  side: CompareSide | null;
}) {
  const isExpected = title === "expected";
  const keys = Array.from(
    new Set([...Object.keys(expected), ...Object.keys(output ?? {})]),
  );

  return (
    <section className="bg-ink-900 px-3 py-3">
      <header className="flex items-baseline justify-between gap-2 border-b border-line pb-1.5">
        <h2 className="text-[13px] text-fg">{title}</h2>
        {side ? (
          <span className="text-[11px] tabular-nums text-fg-mute">
            {side.tool_calls} tool calls · {compactTokens(side.tokens)} tokens
          </span>
        ) : null}
      </header>
      <p className="mt-1 text-[11px] text-fg-mute">{note}</p>

      {output === null ? (
        <Empty>
          Not recorded for this version. A comparison needs a case result at this version; run the
          split it belongs to.
        </Empty>
      ) : (
        <dl className="mt-2">
          {keys.map((key) => {
            const value = output[key];
            const same = stable(value) === stable(expected[key]);
            const tone = isExpected
              ? "text-fg"
              : same
                ? "text-pass"
                : "text-fail";
            return (
              <div key={key} className="border-b border-line-soft py-1.5">
                <dt className="text-[11px] text-fg-mute">{key}</dt>
                <dd className={`text-[12px] break-words ${tone}`}>{render(value)}</dd>
              </div>
            );
          })}
        </dl>
      )}

      {side ? (
        <div className="mt-3">
          <div className="text-[11px] text-fg-mute">
            rules injected {side.rules_injected.length}
          </div>
          {side.rules_injected.length === 0 ? (
            <p className="mt-1 text-[11px] text-fg-mute">
              None. Memory was empty at this version.
            </p>
          ) : (
            <ul className="mt-1 space-y-1.5">
              {side.rules_injected.map((rule) => (
                <li key={rule.id}>
                  <div className="flex items-center gap-1.5">
                    <Pill tone="quiet">{rule.id}</Pill>
                  </div>
                  {rule.rule ? (
                    <p className="prose-h mt-0.5 text-[12px] text-fg-dim">{rule.rule}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return JSON.stringify([...value].map(String).sort());
  return JSON.stringify(value ?? null);
}

function render(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
