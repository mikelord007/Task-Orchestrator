import type { AgentMemory } from "@/lib/types";
import { Empty, Pill } from "@/components/ui";

/**
 * The three memory stores (PLAN.md 0.2). Rules carry the evidence they were
 * written from and the hit/miss record the runtime credited them; a rule that
 * stopped paying is greyed out and marked demoted rather than deleted.
 */
export default function MemoryTab({ memory }: { memory: AgentMemory }) {
  const { rules, tool_notes, episodes } = memory;
  const active = rules.filter((r) => !r.demoted).length;

  return (
    <div className="space-y-6">
      <section>
        <SectionHead
          title="Rules"
          count={rules.length}
          note={`${active} injected, ${rules.length - active} demoted. The runtime injects the top 12 by keyword overlap with the task.`}
        />
        {rules.length === 0 ? (
          <Empty>
            No rules at this version. Reflection writes them after a train run, and the gate has to
            accept them before they are injected. Press <b className="text-fg">Improve</b> to start
            that.
          </Empty>
        ) : (
          <ul>
            {rules.map((rule) => (
              <li
                key={rule.id}
                className={`border-b border-line-soft py-2.5 ${rule.demoted ? "opacity-45" : ""}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] text-fg-mute">{rule.id}</span>
                  {rule.demoted ? (
                    <Pill
                      tone="drift"
                      title={`Demoted at v${rule.demoted_version}: ${rule.misses} misses against ${rule.hits} hits. Kept on disk, no longer injected.`}
                    >
                      demoted
                    </Pill>
                  ) : null}
                  <span className="text-[11px] tabular-nums text-fg-mute">
                    confidence {rule.confidence.toFixed(2)}
                  </span>
                  <span className="text-[11px] tabular-nums">
                    <span className="text-pass">{rule.hits} hits</span>
                    <span className="text-fg-mute"> / </span>
                    <span className={rule.misses > rule.hits ? "text-fail" : "text-fg-mute"}>
                      {rule.misses} misses
                    </span>
                  </span>
                  <span className="text-[11px] text-fg-mute">from v{rule.created_version}</span>
                  <Pill tone="quiet">{rule.source}</Pill>
                </div>
                <p className="prose-h mt-1 text-fg">{rule.rule}</p>
                <div className="mt-1 flex flex-wrap gap-x-4 text-[11px] text-fg-mute">
                  <span>scope: {rule.scope_keywords.join(", ") || "—"}</span>
                  <span>evidence: {rule.evidence_case_ids.join(", ") || "—"}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <SectionHead
          title="Tool notes"
          count={tool_notes.length}
          note="Injected on every task, not filtered by keyword. These are what the agent learned about the tools themselves."
        />
        {tool_notes.length === 0 ? (
          <Empty>
            No tool notes at this version. Reflection writes one when a tool return explains a
            failure — a default parameter, a pagination limit, a field the agent misread.
          </Empty>
        ) : (
          <ul>
            {tool_notes.map((note) => (
              <li key={note.id} className="border-b border-line-soft py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] text-fg-mute">{note.id}</span>
                  <Pill tone="quiet">{note.tool}</Pill>
                  <span className="text-[11px] text-fg-mute">from v{note.created_version}</span>
                </div>
                <p className="prose-h mt-1 text-fg">{note.note}</p>
                <p className="prose-h mt-0.5 text-[12px] text-fg-mute">{note.evidence}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <SectionHead
          title="Episodes"
          count={episodes.length}
          note="One line per run, written by the agent from its own transcript."
        />
        {episodes.length === 0 ? (
          <Empty>
            No episodes yet. One is written after each train run, once there is a transcript and a
            graded outcome to reflect on.
          </Empty>
        ) : (
          <ul>
            {episodes.map((ep) => (
              <li key={ep.run_id} className="flex gap-3 border-b border-line-soft py-1.5">
                <span className="shrink-0 text-[11px] tabular-nums text-fg-mute">v{ep.version}</span>
                <span className="prose-h text-[12px] text-fg-dim">{ep.one_line_reflection}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function SectionHead({ title, count, note }: { title: string; count: number; note: string }) {
  return (
    <header className="border-b border-line pb-1.5">
      <div className="flex items-baseline gap-2">
        <h3 className="text-[13px] text-fg">{title}</h3>
        <span className="text-[11px] tabular-nums text-fg-mute">{count}</span>
      </div>
      <p className="mt-0.5 max-w-[76ch] text-[11px] text-fg-mute">{note}</p>
    </header>
  );
}
