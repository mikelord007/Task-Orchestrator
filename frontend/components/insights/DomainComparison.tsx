import type { InsightsCompare } from "@/lib/types";
import { pct } from "@/lib/format";
import Stat from "@/components/Stat";
import { Empty } from "@/components/ui";

/**
 * The playbook ablation (Domain B, v0, playbook on vs off) as a small stat
 * panel. The side-by-side per-domain pass@1 chart was cut under time pressure
 * (PLAN_ADDENDUM.md sec M cut order) — the ablation numbers are the part of
 * this panel a judge actually needs.
 */
export default function DomainComparison({ compare }: { compare: InsightsCompare | null }) {
  const ablation = compare?.ablation;
  if (!ablation) {
    return (
      <Empty>
        No ablation report yet (reports/ablation.json). Run scripts/playbook_ablation.py to
        produce one.
      </Empty>
    );
  }

  return (
    <div>
      <p className="text-[11px] text-fg-mute">
        playbook ablation · {ablation.domain} · v0 holdout, trials = {ablation.trials}
      </p>
      <div className="mt-2 flex flex-wrap gap-8">
        <Stat
          label="playbook off · pass@1"
          value={`${pct(ablation.playbook_off.pass_at_1)} ± ${pct(ablation.playbook_off.std)}`}
          suffix={`pass^k ${pct(ablation.playbook_off.pass_pow_k)}`}
        />
        <Stat
          label="playbook on · pass@1"
          value={`${pct(ablation.playbook_on.pass_at_1)} ± ${pct(ablation.playbook_on.std)}`}
          suffix={`pass^k ${pct(ablation.playbook_on.pass_pow_k)}`}
          tone="pass"
        />
      </div>
      <p className="mt-2 text-[11px] text-fg-mute">
        applied lessons:{" "}
        {ablation.applied_lesson_ids.length > 0 ? ablation.applied_lesson_ids.join(", ") : "none"}
      </p>
    </div>
  );
}
