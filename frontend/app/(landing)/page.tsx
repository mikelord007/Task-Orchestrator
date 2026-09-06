import Link from "next/link";

const levers = [
  { name: "Memory", detail: "Give experience a place to live.", description: "Turn graded failures into durable lessons the agent can retrieve on its next attempt.", code: "01 / retain what works", glyph: "[ ]" },
  { name: "Tools", detail: "Improve how the agent acts.", description: "Refine the tools available to the agent so the next run can take a better path to the answer.", code: "02 / expand capability", glyph: "</>" },
  { name: "Prompt", detail: "Make the instructions sharper.", description: "Use evidence from failed tasks to clarify the rules, constraints, and reasoning guidance.", code: "03 / clarify intent", glyph: ">_" },
  { name: "Orchestration", detail: "Change how the work gets done.", description: "Adjust the workflow when a different sequence or division of work can solve the underlying failure.", code: "04 / rethink the workflow", glyph: "⊞" },
];

const steps = [
  { name: "Generate", description: "Goal + domain + tools become a versioned agent package." },
  { name: "Evaluate", description: "Run a test suite over configurable trials. Measure the uncertainty." },
  { name: "Reflect", description: "Diagnose graded failures using evidence from actual runs." },
  { name: "Improve", description: "Propose a focused patch through one of four levers." },
  { name: "Gate", description: "Check for regressions. Only passing patches become the next version." },
];

function Arrow({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={className}>↗</span>;
}

function DashboardLink({ className = "" }: { className?: string }) {
  return (
    <Link prefetch={false} href="/agents" className={`inline-flex items-center justify-center gap-6 rounded-xs bg-fg px-5 py-3 text-xs font-medium text-ink-900 transition-colors hover:bg-white ${className}`}>
      Go to Dashboard <Arrow />
    </Link>
  );
}

function EvaluationPreview() {
  return (
    <figure className="relative min-w-0 rounded-lg border border-line bg-ink-800 shadow-2xl shadow-black/30">
      <figcaption className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 text-[10px] text-fg-dim">
        <span className="flex items-center gap-2"><span aria-hidden="true" className="size-1.5 rounded-full bg-fg-mute" /> evaluation / candidate v1</span>
        <span className="rounded-xs border border-line px-2 py-0.5 text-fg-mute">illustrative run</span>
      </figcaption>
      <div className="p-5 sm:p-7">
        <div className="flex items-start justify-between gap-3">
          <div><p className="text-[10px] uppercase tracking-widest text-fg-mute">Agent package</p><p className="mt-2 text-sm">github_triage</p></div>
          <span className="rounded-xs border border-pass/30 bg-pass/5 px-2 py-1 text-[10px] text-pass">✓ gate passed</span>
        </div>
        <div className="my-7 grid grid-cols-2 gap-5">
          <div className="border-l-2 border-train pl-4"><p className="text-[10px] text-train">train / pass@1</p><p className="mt-2 text-3xl tracking-tight">0.88 <span className="text-xs text-fg-mute">± 0.04</span></p></div>
          <div className="border-l-2 border-holdout pl-4"><p className="text-[10px] text-holdout">holdout / pass@1</p><p className="mt-2 text-3xl tracking-tight">0.84 <span className="text-xs text-fg-mute">± 0.05</span></p></div>
        </div>
        <div className="rounded-xs border border-line bg-ink-900 p-4">
          <div className="mb-4 flex justify-between text-[10px] text-fg-mute"><span>trial outcomes</span><span>pass / fail</span></div>
          <div className="space-y-2" aria-label="Illustrative trial outcomes: baseline has five failures; candidate has one failure.">
            {[{ name: "v0", failures: [2, 4, 5, 8, 10] }, { name: "v1", failures: [8] }].map((row) => (
              <div key={row.name} className="flex items-center gap-3">
                <span className="text-[10px] text-fg-mute">{row.name}</span>
                <div aria-hidden="true" className="grid flex-1 grid-cols-12 gap-1">
                  {Array.from({ length: 12 }, (_, i) => <span key={i} className={`h-5 rounded-[2px] border ${row.failures.includes(i) ? "border-fail/40 bg-fail/25" : "border-pass/40 bg-pass/25"}`} />)}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-5 space-y-3 text-[11px]">
          <div className="flex justify-between gap-3"><span className="text-fg-mute">patch lever</span><span>memory</span></div>
          <div className="flex justify-between gap-3"><span className="text-fg-mute">regression check</span><span className="text-pass">passed ✓</span></div>
          <div className="flex justify-between gap-3"><span className="text-fg-mute">decision</span><span className="text-pass">accept candidate</span></div>
        </div>
      </div>
      <div className="border-t border-line px-5 py-3 text-[10px] text-fg-mute sm:px-7">↳ observed events → derived metrics → gate decision</div>
    </figure>
  );
}

export default function LandingPage() {
  return (
    <div className="overflow-x-clip">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-fg focus:p-3 focus:text-ink-900">Skip to content</a>
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-5 px-6 py-5 lg:px-10">
          <Link href="/" aria-label="Task Orchestrator home" className="flex items-center gap-3">
            <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-xs border border-fg-mute text-lg">⌘</span>
            <span className="text-xs leading-tight">task<span className="block text-fg-mute">orchestrator</span></span>
          </Link>
          <nav aria-label="Landing navigation" className="flex items-center gap-7 text-[11px]">
            <a href="#loop" className="hidden text-fg-dim transition-colors hover:text-fg sm:block">How it works</a>
            <a href="#levers" className="hidden text-fg-dim transition-colors hover:text-fg md:block">Four levers</a>
            <Link prefetch={false} href="/agents" className="flex items-center gap-3 rounded-xs border border-line px-4 py-2 transition-colors hover:border-fg-mute">Dashboard <Arrow /></Link>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="relative mx-auto grid max-w-7xl items-center gap-14 px-6 pb-20 pt-16 lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:px-10 lg:pb-24 lg:pt-24">
          <div>
            <p className="mb-7 flex items-center gap-3 text-[10px] uppercase tracking-[0.2em] text-fg-dim"><span className="h-px w-7 bg-fg-mute" aria-hidden="true" /> The agent improvement engine</p>
            <h1 className="font-sans text-5xl font-medium leading-[1.05] tracking-[-0.045em] sm:text-6xl xl:text-7xl">Build an agent.<br />Make it better.<br /><span className="text-fg-mute">Prove it.</span></h1>
            <p className="mt-7 max-w-md font-sans text-lg leading-relaxed text-fg-dim">Task Orchestrator turns a goal into an agent, learns from its failures, and tests every improvement before it lands.</p>
            <div className="mt-9 flex flex-wrap items-center gap-6"><DashboardLink /><a href="#loop" className="text-xs text-fg-dim hover:text-fg">Explore the loop <span aria-hidden="true">↓</span></a></div>
            <p className="mt-5 text-[10px] text-fg-mute">Four levers. One regression gate. Every event recorded.</p>
          </div>
          <EvaluationPreview />
        </section>

        <div className="border-y border-line bg-ink-800/40">
          <div className="mx-auto grid max-w-7xl grid-cols-1 gap-5 px-6 py-6 text-[11px] text-fg-dim sm:grid-cols-3 lg:px-10">
            <p className="flex items-center gap-3"><span className="text-pass" aria-hidden="true">✓</span> Regression-gated improvements</p>
            <p className="flex items-center gap-3"><span aria-hidden="true" className="text-fg-mute">≡</span> Append-only evidence ledger</p>
            <p className="flex items-center gap-3"><span aria-hidden="true" className="text-fg-mute">↗</span> Lessons that transfer across agents</p>
          </div>
        </div>

        <section id="loop" aria-labelledby="loop-title" className="mx-auto max-w-7xl scroll-mt-8 px-6 py-20 lg:px-10 lg:py-24">
          <p className="text-[10px] uppercase tracking-[0.2em] text-fg-mute">01 / The improvement loop</p>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-6">
            <h2 id="loop-title" className="max-w-lg font-sans text-3xl font-medium tracking-tight sm:text-4xl">From first attempt<br />to measured improvement.</h2>
            <p className="max-w-sm font-sans text-base leading-relaxed text-fg-dim">A repeatable cycle that connects each change to the evidence behind it.</p>
          </div>
          <ol className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {steps.map((step, i) => (
              <li key={step.name} className={`relative border-t p-5 ${i === 4 ? "border-pass/60 bg-pass/5" : "border-line bg-ink-800/60"}`}>
                <div className="flex justify-between text-[11px] text-fg-mute"><span>0{i + 1}</span><span aria-hidden="true" className={i === 4 ? "text-pass" : ""}>{i === 4 ? "✓" : "→"}</span></div>
                <h3 className="mt-6 text-sm">{step.name}</h3>
                <p className="mt-3 font-sans text-sm leading-relaxed text-fg-dim">{step.description}</p>
              </li>
            ))}
          </ol>
          <div className="mt-4 flex items-center gap-3 text-[10px] text-fg-mute"><span aria-hidden="true">↳</span><p>Accepted version → evaluate again <span className="mx-2">/</span> Rejected patch → keep the prior version</p></div>
        </section>

        <section id="levers" aria-labelledby="levers-title" className="border-y border-line bg-ink-800/30">
          <div className="mx-auto max-w-7xl px-6 py-20 lg:px-10 lg:py-24">
            <p className="text-[10px] uppercase tracking-[0.2em] text-fg-mute">02 / Four improvement levers</p>
            <h2 id="levers-title" className="mt-4 font-sans text-3xl font-medium tracking-tight sm:text-4xl">More than a better prompt.</h2>
            <p className="mt-5 max-w-xl font-sans text-base leading-relaxed text-fg-dim">Start with memory, then tools, prompt, and orchestration. Match the intervention to the failure, and change one lever at a time.</p>
            <div className="mt-12 grid gap-px overflow-hidden rounded-sm border border-line bg-line md:grid-cols-2">
              {levers.map((lever) => (
                <article key={lever.name} className="group bg-ink-900 p-7 transition-colors hover:bg-ink-800 sm:p-9">
                  <div className="flex items-center justify-between"><span aria-hidden="true" className="text-2xl text-fg-mute transition-colors group-hover:text-fg">{lever.glyph}</span><span className="text-[9px] uppercase tracking-widest text-fg-mute">{lever.code}</span></div>
                  <h3 className="mt-8 font-sans text-2xl font-medium">{lever.name}</h3>
                  <p className="mt-2 font-sans text-base text-fg">{lever.detail}</p>
                  <p className="mt-3 max-w-md font-sans text-sm leading-relaxed text-fg-dim">{lever.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="evidence-title" className="mx-auto max-w-7xl px-6 py-20 lg:px-10 lg:py-24">
          <div className="grid gap-12 lg:grid-cols-[0.85fr_1.15fr] lg:gap-24">
            <div>
              <p className="text-[10px] uppercase tracking-[0.2em] text-fg-mute">03 / Evidence by design</p>
              <h2 id="evidence-title" className="mt-4 font-sans text-3xl font-medium tracking-tight sm:text-4xl">Every claim<br />has a paper trail.</h2>
              <p className="mt-5 font-sans text-base leading-relaxed text-fg-dim">Reflection starts from graded failures, not an agent’s self-report. Improvement has to survive evaluation.</p>
              <div className="mt-8 border-l border-pass/50 pl-5"><p className="text-xs text-pass">The regression gate</p><p className="mt-3 font-sans text-sm leading-relaxed text-fg-dim">A patch only lands if it passes the gate’s regression checks. Failed candidates stay in the record; the prior agent version stays in place.</p></div>
            </div>
            <div className="divide-y divide-line border-y border-line">
              {[
                { label: "01", title: "An append-only ledger", text: "Observed facts go in. Metrics come out as queries. Every number is derived from events; nothing is stored as a status." },
                { label: "02", title: "Evaluation without the answer key", text: "Ground-truth redaction keeps expected answers out of the agent’s inputs. The evaluator can grade what the agent cannot see." },
                { label: "03", title: "Uncertainty stays visible", text: "Configurable trials and error bars put pass@1 in context. Track pass^k to see whether success holds across repeated attempts." },
                { label: "04", title: "A playbook that compounds", text: "Extract reusable lessons from one agent’s runs into a shared playbook. Give the next agent a stronger starting point." },
              ].map((feature) => (
                <article key={feature.label} className="flex gap-5 py-6"><span className="pt-1 text-[10px] text-fg-mute">{feature.label}</span><div><h3 className="font-sans text-lg font-medium">{feature.title}</h3><p className="mt-2 font-sans text-sm leading-relaxed text-fg-dim">{feature.text}</p></div></article>
              ))}
            </div>
          </div>
        </section>

        <section className="border-y border-line bg-ink-800/50 px-6 py-16 text-center lg:py-20">
          <p className="text-[10px] uppercase tracking-[0.2em] text-fg-mute">Generate. Measure. Improve. Prove.</p>
          <h2 className="mt-5 font-sans text-3xl font-medium tracking-tight sm:text-4xl">Give your next agent a feedback loop.</h2>
          <p className="mt-4 font-sans text-base text-fg-dim">Start with a goal. Build a record of what works.</p>
          <DashboardLink className="mt-8" />
        </section>
      </main>

      <footer className="mx-auto flex max-w-7xl flex-wrap justify-between gap-4 px-6 py-7 text-[10px] text-fg-mute lg:px-10"><p>task orchestrator <span className="mx-2 text-line">/</span> Built for the next iteration.</p><a className="hover:text-fg" href="https://github.com/mikelord007/Task-Orchestrator">View source <Arrow /></a></footer>
    </div>
  );
}
