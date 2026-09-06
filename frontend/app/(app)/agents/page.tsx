"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { createAgent, listAgents, listEvaluators, LIVE_MODEL_CALLS } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import Stat from "@/components/Stat";
import { Button, Empty, Field, PageHeader, Panel, Pill, inputClass } from "@/components/ui";

export default function AgentsPage() {
  const agents = useAsync(() => listAgents(), []);
  const evaluators = useAsync(() => listEvaluators(), []);
  const [formOpen, setFormOpen] = useState(false);

  return (
    <div className="mx-auto max-w-[1360px] px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader
        title="Agents"
        subtitle="Each agent is a versioned package. A version is only ever added, never edited in place."
        right={
          <Button
            variant="primary"
            disabled={!LIVE_MODEL_CALLS}
            onClick={() => setFormOpen((v) => !v)}
            title={LIVE_MODEL_CALLS ? undefined : "Unavailable: no model provider credentials are configured"}
          >
            {formOpen ? "Close" : "New agent"}
          </Button>
        }
      />

      {formOpen ? (
        <NewAgentForm
          evaluators={evaluators.data ?? []}
          onCreated={() => {
            setFormOpen(false);
            agents.reload();
          }}
        />
      ) : null}

      <Panel
        title="All agents"
        meta={agents.data ? `${agents.data.length}` : undefined}
        className="mt-7"
      >
        {agents.loading ? (
          <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
        ) : agents.error ? (
          <Empty>Could not reach the backend: {agents.error}</Empty>
        ) : (agents.data?.length ?? 0) === 0 ? (
          <Empty>
            No agents are stored in the live backend. Generating a new one is unavailable because
            no model provider credentials are configured.
          </Empty>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {agents.data!.map((agent) => (
              <article
                key={agent.agent_id}
                className="group flex min-w-0 flex-col rounded-lg border border-line bg-ink-900/50 p-5 transition-colors hover:border-fg-mute/60 hover:bg-ink-800"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      href={`/agents/${agent.agent_id}`}
                      className="break-words font-sans text-lg font-medium text-fg underline-offset-4 hover:underline"
                    >
                      {agent.name}
                      <span
                        aria-hidden="true"
                        className="ml-2 inline-block text-fg-mute transition-transform group-hover:translate-x-0.5"
                      >
                        ↗
                      </span>
                    </Link>
                    <div className="mt-1 break-all text-[10px] text-fg-mute">{agent.agent_id}</div>
                  </div>
                  <Pill>v{agent.current_version}</Pill>
                </div>
                <div className="mt-4">
                  <Pill tone="quiet">{agent.domain}</Pill>
                </div>
                <p className="prose-h mt-3 flex-1 break-words text-fg-dim">{agent.goal}</p>
                <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2 border-t border-line pt-4">
                  <Stat label="train" rate={agent.latest_train} tone="train" size="md" />
                  <Stat label="holdout" rate={agent.latest_holdout} tone="holdout" size="md" />
                </div>
              </article>
            ))}
          </div>
        )}
        {(agents.data?.length ?? 0) > 0 ? (
          <p className="mt-5 text-[11px] leading-5 text-fg-mute">
            Pass rates are the latest recorded run of the current version, mean ± std over trials. A
            dash means that split has not been run.
          </p>
        ) : null}
      </Panel>
    </div>
  );
}

function NewAgentForm({
  evaluators,
  onCreated,
}: {
  evaluators: {
    evaluator_id: string;
    domain: string;
    description: string;
    allowed_tools: string[];
  }[];
  onCreated: () => void;
}) {
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [evaluatorId, setEvaluatorId] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [usePlaybook, setUsePlaybook] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evaluator = useMemo(
    () => evaluators.find((e) => e.evaluator_id === evaluatorId) ?? evaluators[0],
    [evaluators, evaluatorId],
  );
  const allowedTools = evaluator?.allowed_tools ?? [];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!evaluator) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createAgent({
        goal,
        domain: evaluator.domain,
        tools,
        evaluator_id: evaluator.evaluator_id,
        use_playbook: usePlaybook,
      });
      onCreated();
      router.push(`/agents/${created.agent_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  if (evaluators.length === 0) {
    return (
      <Panel title="New agent" className="mt-7">
        <Empty>
          No evaluators are registered. Add one under <code>evaluators/</code> and reload; the tool
          list on this form comes from the evaluator.
        </Empty>
      </Panel>
    );
  }

  return (
    <Panel title="New agent" className="mt-7">
      <p className="mb-6 font-sans text-sm text-fg-dim">
        Define a goal, choose an evaluator, and equip your first version.
      </p>
      <form onSubmit={submit} className="grid gap-6 md:grid-cols-2">
        <div className="md:col-span-2">
          <Field
            label="Goal"
            hint="One sentence. The architect reads this alongside the evaluator README and five sample train tasks."
          >
            <textarea
              required
              rows={3}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="Triage an open issue the way this repository's maintainers do."
              className={inputClass}
            />
          </Field>
        </div>

        <Field label="Evaluator" hint={evaluator?.description}>
          <select
            value={evaluator?.evaluator_id}
            onChange={(e) => {
              setEvaluatorId(e.target.value);
              setTools([]);
            }}
            className={inputClass}
          >
            {evaluators.map((ev) => (
              <option key={ev.evaluator_id} value={ev.evaluator_id}>
                {ev.evaluator_id}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Domain" hint="Taken from the evaluator.">
          <input
            readOnly
            value={evaluator?.domain ?? ""}
            className={`${inputClass} text-fg-mute`}
          />
        </Field>

        <div className="md:col-span-2">
          <Field
            label={`Tools (${tools.length} of ${allowedTools.length})`}
            hint="Only the tools this evaluator allows. The architect may still write one glue tool of its own."
          >
            <div className="mt-3 flex flex-wrap gap-2">
              {allowedTools.map((tool) => {
                const on = tools.includes(tool);
                return (
                  <button
                    type="button"
                    key={tool}
                    aria-pressed={on}
                    onClick={() =>
                      setTools((prev) =>
                        prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
                      )
                    }
                    className={`rounded-lg border px-3 py-2 text-[11px] transition-colors ${
                      on
                        ? "border-fg-dim bg-ink-600 text-fg"
                        : "border-line bg-ink-900 text-fg-dim hover:border-fg-mute hover:text-fg"
                    }`}
                  >
                    {tool}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>

        <div className="md:col-span-2 flex flex-wrap items-center gap-4 border-t border-line pt-5">
          <label className="flex flex-wrap items-center gap-2 text-[12px] text-fg-dim">
            <input
              type="checkbox"
              checked={usePlaybook}
              onChange={(e) => setUsePlaybook(e.target.checked)}
              className="h-4 w-4 accent-fg"
            />
            Apply the playbook
            <span className="text-[11px] text-fg-mute">
              (lessons learned improving other agents; the architect records which it used)
            </span>
          </label>
          <Button type="submit" variant="primary" disabled={busy || !goal || tools.length === 0}>
            {busy ? "Generating v0…" : "Generate v0"}
          </Button>
          {tools.length === 0 ? (
            <span className="text-[11px] text-fg-mute">Pick at least one tool.</span>
          ) : null}
        </div>

        {error ? <p className="md:col-span-2 text-[12px] text-fail">{error}</p> : null}
      </form>
    </Panel>
  );
}
