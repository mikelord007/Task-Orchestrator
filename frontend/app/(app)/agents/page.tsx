"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { createAgent, listAgents, listEvaluators } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import Stat from "@/components/Stat";
import { Button, Empty, Field, PageHeader, Panel, Td, Th, inputClass } from "@/components/ui";

export default function AgentsPage() {
  const agents = useAsync(() => listAgents(), []);
  const evaluators = useAsync(() => listEvaluators(), []);
  const [formOpen, setFormOpen] = useState(false);

  return (
    <div className="mx-auto max-w-[1360px] px-6 py-5">
      <PageHeader
        title="Agents"
        subtitle="Each agent is a versioned package. A version is only ever added, never edited in place."
        right={
          <Button variant="primary" onClick={() => setFormOpen((v) => !v)}>
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
        className="mt-5"
      >
        {agents.loading ? (
          <p className="py-3 text-[12px] text-fg-mute">Loading…</p>
        ) : agents.error ? (
          <Empty>Could not reach the backend: {agents.error}</Empty>
        ) : (agents.data?.length ?? 0) === 0 ? (
          <Empty>
            No agents yet. Press <b className="text-fg">New agent</b> to generate a v0 package from
            a goal, a tool set and an evaluator.
          </Empty>
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr>
                <Th className="w-[22%]">agent</Th>
                <Th className="w-[14%]">domain</Th>
                <Th className="w-[7%]">version</Th>
                <Th className="w-[16%]">train</Th>
                <Th className="w-[16%]">holdout</Th>
                <Th>goal</Th>
              </tr>
            </thead>
            <tbody>
              {agents.data!.map((agent) => (
                <tr key={agent.agent_id}>
                  <Td>
                    <Link
                      href={`/agents/${agent.agent_id}`}
                      className="text-fg hover:text-train hover:underline"
                    >
                      {agent.name}
                    </Link>
                    <div className="text-[11px] text-fg-mute">{agent.agent_id}</div>
                  </Td>
                  <Td className="text-fg-dim">{agent.domain}</Td>
                  <Td className="tabular-nums text-fg-dim">v{agent.current_version}</Td>
                  <Td>
                    <Stat label="" rate={agent.latest_train} tone="train" size="sm" />
                  </Td>
                  <Td>
                    <Stat label="" rate={agent.latest_holdout} tone="holdout" size="sm" />
                  </Td>
                  <Td className="text-fg-dim">
                    <span className="prose-h block">{agent.goal}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(agents.data?.length ?? 0) > 0 ? (
          <p className="mt-2 text-[10px] text-fg-mute">
            Pass rates are the latest recorded run of the current version, mean ± std over trials.
            A dash means that split has not been run.
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
  evaluators: { evaluator_id: string; domain: string; description: string; allowed_tools: string[] }[];
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
      <Panel title="New agent" className="mt-5">
        <Empty>
          No evaluators are registered. Add one under <code>evaluators/</code> and reload; the tool
          list on this form comes from the evaluator.
        </Empty>
      </Panel>
    );
  }

  return (
    <Panel title="New agent" className="mt-5">
      <form onSubmit={submit} className="grid max-w-[900px] gap-4 py-2 md:grid-cols-2">
        <div className="md:col-span-2">
          <Field
            label="Goal"
            hint="One sentence. The architect reads this alongside the evaluator README and five sample train tasks."
          >
            <textarea
              required
              rows={2}
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
          <input readOnly value={evaluator?.domain ?? ""} className={`${inputClass} text-fg-mute`} />
        </Field>

        <div className="md:col-span-2">
          <Field
            label={`Tools (${tools.length} of ${allowedTools.length})`}
            hint="Only the tools this evaluator allows. The architect may still write one glue tool of its own."
          >
            <div className="mt-1 flex flex-wrap gap-1.5">
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
                    className={`rounded-xs border px-2 py-1 text-[11px] ${
                      on
                        ? "border-train/50 bg-train/10 text-train"
                        : "border-line text-fg-mute hover:border-fg-mute hover:text-fg-dim"
                    }`}
                  >
                    {tool}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>

        <div className="md:col-span-2 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-[12px] text-fg-dim">
            <input
              type="checkbox"
              checked={usePlaybook}
              onChange={(e) => setUsePlaybook(e.target.checked)}
              className="accent-train"
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
