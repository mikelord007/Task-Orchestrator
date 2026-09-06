import Link from "next/link";
import Brand from "@/components/Brand";

const loop = [
  ["01", "Generate", "We turn a goal, domain, and tool boundary into a versioned agent package."],
  ["02", "Evaluate", "We run the configured task suite and keep uncertainty attached to every rate."],
  ["03", "Reflect", "We diagnose graded failures from recorded runs, not from the agent’s self-report."],
  ["04", "Improve", "We change one lever against a named failure group and preserve the evidence."],
  ["05", "Gate", "We accept the candidate only when the regression checks hold."],
] as const;

const levers = [
  ["01 / memory", "Retain what works", "Convert graded failures into scoped rules and tool notes that can be retrieved on the next attempt."],
  ["02 / tools", "Change what the agent can do", "Refine tool boundaries and behavior when execution, not instruction, limits the result."],
  ["03 / prompt", "Clarify the operating rules", "Edit instructions when the evidence points to ambiguity, ordering, or missing constraints."],
  ["04 / orchestration", "Recompose the work", "Adjust the sequence or division of work when the workflow itself creates the failure."],
] as const;

function DashboardLink({ secondary = false, accentArrow = false }: { secondary?: boolean; accentArrow?: boolean }) {
  return (
    <Link
      prefetch={false}
      href="/agents"
      className={secondary
        ? "inline-flex border border-line px-4 py-3 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-fg-dim hover:border-[#ff9783] hover:text-[#ff9783]"
        : "inline-flex border border-fg bg-fg px-4 py-3 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-ink-900 hover:border-[#ff9783] hover:bg-[#ff9783]"}
    >
      <span><span className="hidden sm:inline">Open </span>dashboard</span><span aria-hidden="true" className={`ml-8 ${accentArrow ? "text-[#ff563c]" : "text-current"}`}>→</span>
    </Link>
  );
}

function EmptySystemRecord() {
  return (
    <aside aria-label="Evaluation record preview" className="border border-line-soft bg-ink-700">
      <header className="flex items-center justify-between gap-4 border-b-2 border-line-soft px-5 py-4">
        <span className="small-label text-fg">Evaluation record</span>
        <span className="border border-line bg-ink-600 px-2 py-1 font-mono text-[10px] uppercase text-fg-mute">No run selected</span>
      </header>
      <div className="grid gap-5 p-5 sm:p-6">
        <div>
          <p className="small-label">Agent package</p>
          <div className="mt-2 border border-dashed border-fg-mute bg-ink-600 px-3 py-4 font-mono text-[12px] text-fg-mute">awaiting a recorded package</div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="small-label">Train / pass@1</p>
            <p className="metric-value mt-2 text-3xl text-fg-mute">—</p>
          </div>
          <div>
            <p className="small-label">Holdout / pass@1</p>
            <p className="metric-value mt-2 text-3xl text-fg-mute">—</p>
          </div>
        </div>
        <div className="border border-dashed border-fg-mute bg-ink-600 p-4">
          <p className="small-label">Version trace</p>
          <div className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 font-mono text-[11px]">
            <span className="text-fg-mute">v0</span><span className="h-4 border border-dashed border-fg-mute" />
            <span className="text-fg-mute">v1</span><span className="h-4 border border-dashed border-fg-mute" />
          </div>
        </div>
      </div>
      <footer className="flex justify-between gap-4 border-t-2 border-line-soft px-5 py-4 font-mono text-[10px] uppercase tracking-[0.08em] text-fg-mute sm:px-6">
        <span>Observed events → derived metrics</span>
        <span>00 / empty</span>
      </footer>
    </aside>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-screen overflow-x-clip bg-ink-800">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-fg focus:p-3 focus:text-ink-900">Skip to content</a>
      <header className="border-b-2 border-line-soft bg-ink-900">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 px-5 py-5 sm:px-8 lg:px-12">
          <Brand />
          <nav aria-label="Landing navigation" className="flex items-center gap-5 font-mono text-[10px] uppercase tracking-[0.08em]">
            <a href="#method" className="hidden text-fg-mute hover:text-[#ff9783] sm:block">Method</a>
            <a href="#levers" className="hidden text-fg-mute hover:text-[#ff9783] md:block">Levers</a>
            <DashboardLink secondary />
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="mx-auto grid max-w-[1440px] min-w-0 gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[minmax(0,1.12fr)_minmax(360px,.88fr)] lg:items-end lg:gap-16 lg:px-12 lg:py-24">
          <div className="min-w-0">
            <p className="eyebrow">Agent improvement / evidence first</p>
            <span aria-hidden="true" className="mt-6 block h-1 w-16 bg-[#ff563c]" />
            <h1 className="display-type mt-7 max-w-[900px] text-[clamp(3.25rem,8vw,7.75rem)] text-fg">Build the agent. Measure the change.</h1>
            <p className="mt-7 max-w-2xl text-lg leading-[1.42] text-fg-body sm:text-xl">We turn a goal into a versioned agent, learn from its recorded failures, and test each candidate before it becomes current.</p>
            <div className="mt-9 flex flex-wrap gap-4">
              <DashboardLink accentArrow />
              <a href="#method" className="inline-flex border border-line px-4 py-3 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-fg-dim hover:border-[#ff9783] hover:text-[#ff9783]">Read the method</a>
            </div>
          </div>
          <EmptySystemRecord />
        </section>

        <div className="border-y-2 border-line-soft bg-ink-900">
          <div className="mx-auto grid max-w-[1440px] divide-y divide-line-soft px-5 font-mono text-[11px] uppercase tracking-[0.06em] text-fg-mute sm:grid-cols-3 sm:divide-x sm:divide-y-0 sm:px-8 lg:px-12">
            <p className="py-5 sm:pr-6">Regression-gated changes</p>
            <p className="py-5 sm:px-6">Append-only evidence</p>
            <p className="py-5 sm:pl-6">Versioned agent packages</p>
          </div>
        </div>

        <section id="method" aria-labelledby="method-title" className="scroll-mt-4 border-b-2 border-line-soft">
          <div className="mx-auto max-w-[1440px] px-5 py-16 sm:px-8 lg:px-12 lg:py-20">
            <p className="eyebrow">01 / Improvement loop</p>
            <div className="mt-5 grid gap-6 lg:grid-cols-2 lg:items-end">
              <h2 id="method-title" className="display-type max-w-2xl text-4xl text-fg sm:text-6xl">One change. One gate. A record that remains.</h2>
              <p className="max-w-xl text-base text-fg-dim sm:text-lg">The loop connects each intervention to the failures behind it and keeps rejected work visible as evidence.</p>
            </div>
            <ol className="mt-12 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              {loop.map(([number, title, copy]) => (
                <li key={number} className="flex flex-col border border-line-soft bg-ink-700 p-6">
                  <span className="small-label">{number} / 05</span>
                  <h3 className="mt-10 font-sans text-2xl font-bold text-fg">{title}</h3>
                  <p className="mt-4 text-sm leading-[1.45] text-fg-dim">{copy}</p>
                  <span aria-hidden="true" className="mt-auto pt-8 font-mono text-lg text-fg-mute">{number === "05" ? "■" : "→"}</span>
                </li>
              ))}
            </ol>
            <footer className="mt-8 flex flex-wrap justify-between gap-4 border-t-2 border-line-soft pt-5 font-mono text-[11px] uppercase tracking-[0.06em] text-fg-mute">
              <span>Accepted candidate → next current version</span>
              <span>Rejected candidate → prior version remains</span>
            </footer>
          </div>
        </section>

        <section id="levers" aria-labelledby="levers-title" className="scroll-mt-4 border-b-2 border-line-soft bg-ink-900">
          <div className="mx-auto max-w-[1440px] px-5 py-16 sm:px-8 lg:px-12 lg:py-20">
            <p className="eyebrow">02 / Four levers</p>
            <h2 id="levers-title" className="display-type mt-5 max-w-3xl text-4xl text-fg sm:text-6xl">The prompt is one part of the system.</h2>
            <div className="mt-12 grid gap-4 md:grid-cols-2">
              {levers.map(([label, title, copy]) => (
                <article key={label} className="border border-line-soft bg-ink-700 p-7 sm:p-8">
                  <p className="small-label">{label}</p>
                  <h3 className="mt-10 font-sans text-3xl font-bold text-fg">{title}</h3>
                  <p className="mt-4 max-w-xl text-base leading-[1.45] text-fg-dim">{copy}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="evidence-title" className="border-b-2 border-line-soft">
          <div className="mx-auto grid max-w-[1440px] gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[.8fr_1.2fr] lg:px-12 lg:py-20">
            <div>
              <p className="eyebrow">03 / Evidence model</p>
              <h2 id="evidence-title" className="display-type mt-5 text-4xl text-fg sm:text-6xl">Every claim keeps its paper trail.</h2>
            </div>
            <div className="border-y-2 border-line-soft">
              {[
                ["Ledger", "Observed events are stored first. Metrics and statuses are derived from queries over that record."],
                ["Evaluation", "Expected answers stay outside the agent input while evaluators grade the recorded output."],
                ["Uncertainty", "Repeated trials keep variance visible instead of collapsing performance into a single unqualified score."],
                ["Playbook", "Accepted fixes can become reusable lessons with their source agent and evidence attached."],
              ].map(([title, copy], index) => (
                <article key={title} className="grid gap-3 border-b border-line-soft py-6 last:border-b-0 sm:grid-cols-[80px_1fr]">
                  <span className="small-label">0{index + 1}</span>
                  <div><h3 className="font-sans text-xl font-bold text-fg">{title}</h3><p className="mt-2 max-w-2xl text-sm text-fg-dim">{copy}</p></div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="bg-[#ff563c]">
          <div className="mx-auto max-w-[1440px] px-5 py-14 sm:px-8 lg:px-12 lg:py-20">
            <p className="small-label text-ink-900">Regression gate / decision rule</p>
            <p className="display-type mt-5 max-w-6xl text-4xl text-ink-900 sm:text-6xl lg:text-7xl">A failed candidate is evidence, not the next version.</p>
          </div>
        </section>

        <section className="border-b-2 border-line-soft bg-ink-900">
          <div className="mx-auto grid max-w-[1440px] gap-8 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_auto] lg:items-end lg:px-12 lg:py-20">
            <div><p className="eyebrow">04 / Control surface</p><h2 className="display-type mt-5 max-w-3xl text-4xl text-fg sm:text-6xl">Inspect the system from its real data.</h2></div>
            <DashboardLink />
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-[1440px] flex-wrap justify-between gap-4 px-5 py-7 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-mute sm:px-8 lg:px-12">
        <span>Task Orchestrator / public demonstration</span>
        <a href="https://github.com/mikelord007/Task-Orchestrator" className="text-[#ff563c] hover:text-[#ff9783]">View source</a>
      </footer>
    </div>
  );
}
