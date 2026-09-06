"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { compareCase, getAgent, listFixes, listRuns } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import type { CompareSide, Json } from "@/lib/types";
import { compactTokens, pct } from "@/lib/format";
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
  // GET /agents/{id} and GET /agents/{id}/runs may not be wired up yet (still
  // merging as of this writing); the fixes list is real today and doubles as
  // a source of case ids and rule text so this page stays useful either way.
  const fixes = useAsync(() => listFixes(agentId), [agentId]);
  const result = useAsync(
    () => (caseId ? compareCase(agentId, caseId) : Promise.resolve(null)),
    [agentId, caseId],
  );

  const cases = useMemo(() => {
    const seen = new Set<string>();
    for (const run of runs.data ?? []) for (const t of run.tasks) seen.add(t.case_id);
    for (const card of fixes.data ?? []) {
      for (const id of card.failing_group.case_ids) seen.add(id);
      for (const id of card.regressed_case_ids ?? []) seen.add(id);
    }
    return Array.from(seen).sort();
  }, [runs.data, fixes.data]);

  const ruleText = useMemo(() => {
    const map: Record<string, string> = {};
    for (const rule of agent.data?.memory.rules ?? []) map[rule.id] = rule.rule;
    for (const card of fixes.data ?? []) {
      for (const entry of card.memory_entries ?? []) {
        if (entry.kind === "rule" && entry.rule) map[entry.id] = entry.rule;
      }
    }
    return map;
  }, [agent.data, fixes.data]);

  function pick(id: string) {
    router.replace(`/agents/${agentId}/compare?case_id=${encodeURIComponent(id)}`, {
      scroll: false,
    });
  }

  const currentVersion = agent.data?.current_version ?? 0;

  return (
    <div className="mx-auto max-w-[1440px] px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
      <div className="mb-2 text-[11px]">
        <Crumb href="/agents">agents</Crumb>
        <span className="text-fg-mute"> / </span>
        <Crumb href={`/agents/${agentId}`}>{agentId}</Crumb>
        <span className="text-fg-mute"> / compare</span>
      </div>

      <PageHeader
        title="Compare one task across versions"
        subtitle="The same input, graded against the same expected answer, at v0 and at the current version. Matching fields are white; differing fields are red."
      />

      <div className="mt-5 border-b-2 border-line-soft pb-4">
        <div className="small-label">task</div>
        {runs.loading ? (
          <p className="text-[12px] text-fg-mute">Loading tasks…</p>
        ) : cases.length === 0 ? (
          <Empty>
            No tasks to compare. Run a split on this agent first; the picker lists every task that
            appears in a recorded run.
          </Empty>
        ) : (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {cases.map((id) => (
              <button
                key={id}
                onClick={() => pick(id)}
                aria-pressed={id === caseId}
                className={`border px-2 py-1 font-mono text-[10px] ${
                  id === caseId
                    ? "border-fg bg-fg text-ink-900"
                    : "border-line text-fg-mute hover:border-[#ff9783] hover:text-[#ff9783]"
                }`}
              >
                {id}
              </button>
            ))}
          </div>
        )}
      </div>

      {!caseId ? (
        <Empty>Pick a task above. This page is deep-linkable as ?case_id=&lt;id&gt;.</Empty>
      ) : result.loading ? (
        <p className="py-4 text-[12px] text-fg-mute">Loading {caseId}…</p>
      ) : result.error ? (
        <Empty>Could not load {caseId}: {result.error}</Empty>
      ) : !result.data ? null : (
        <div className="grid gap-4 pt-6 md:grid-cols-3">
          <Column
            title="expected"
            note="Ground truth from the evaluator."
            output={result.data.expected}
            expected={result.data.expected}
            side={null}
            ruleText={ruleText}
          />
          <Column
            title="v0"
            note="The generated agent, before any improvement."
            output={result.data.v0?.output ?? null}
            expected={result.data.expected}
            side={result.data.v0}
            ruleText={ruleText}
          />
          <Column
            title={`v${currentVersion}`}
            note="The current version."
            output={result.data.current?.output ?? null}
            expected={result.data.expected}
            side={result.data.current}
            ruleText={ruleText}
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
  ruleText,
}: {
  title: string;
  note: string;
  output: Json | null;
  expected: Json;
  side: CompareSide | null;
  ruleText: Record<string, string>;
}) {
  const isExpected = title === "expected";
  const keys = Array.from(
    new Set([...Object.keys(expected), ...Object.keys(output ?? {})]),
  );

  return (
    <section className="border border-line-soft bg-ink-700 p-5">
      <header className="flex items-baseline justify-between gap-2 border-b-2 border-line-soft pb-4">
        <div className="flex items-baseline gap-1.5">
          <h2 className="text-[13px] text-fg">{title}</h2>
          {side?.passed !== undefined ? (
            <Pill tone={side.passed ? "pass" : "fail"}>
              {side.passed ? "passed" : "failed"}
              {side.score !== undefined ? ` · ${pct(side.score, 0)}` : ""}
            </Pill>
          ) : null}
        </div>
        {side ? (
          <span className="text-[11px] tabular-nums text-fg-mute">
            {side.tool_calls} tool calls · {compactTokens(side.tokens)} tokens
          </span>
        ) : null}
      </header>
      <p className="mt-1 text-[11px] text-fg-mute">{note}</p>

      {output === null ? (
        <Empty>
          Not recorded for this version. A comparison needs a task result at this version; run the
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
              {side.rules_injected.map((ruleId) => (
                <li key={ruleId}>
                  <div className="flex items-center gap-1.5">
                    <Pill tone="quiet">{ruleId}</Pill>
                  </div>
                  {ruleText[ruleId] ? (
                    <p className="prose-h mt-0.5 text-[12px] text-fg-dim">{ruleText[ruleId]}</p>
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
