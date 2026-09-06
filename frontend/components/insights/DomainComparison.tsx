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
        playbook ablation · {ablation.domain} · v0 holdout pass@1
      </p>
      <div className="mt-2 flex flex-wrap gap-8">
        <Stat
          label="playbook off"
          value={`${pct(ablation.playbook_off.holdout_mean)} ± ${pct(ablation.playbook_off.holdout_std)}`}
        />
        <Stat
          label="playbook on"
          value={`${pct(ablation.playbook_on.holdout_mean)} ± ${pct(ablation.playbook_on.holdout_std)}`}
          tone="pass"
        />
      </div>
      <p className="mt-2 text-[11px] text-fg-mute">
        applied lessons:{" "}
        {ablation.applied_lessons.length > 0 ? ablation.applied_lessons.join(", ") : "none"}
      </p>
    </div>
  );
}
