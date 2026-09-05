# Playbook contract

PLAN.md §4.4. **Frozen after Phase 0.**

The playbook is how improving *one* agent makes the *next* agent — in a
different domain — start better. It is the evidence that the **system**
improves, not just a single agent.

## `playbook/lessons.jsonl`

One JSON object per line:

```json
{"id": "lesson_7c1d",
 "lever": "memory",
 "trigger": "agent must map free-text reports to a fixed label vocabulary",
 "lesson": "Write one rule per label describing the signal that selects it, with the evidence case ids; inject only rules whose keywords overlap the input.",
 "domain_tags": ["classification", "triage"],
 "source_agent_id": "a_github_triage_1",
 "source_issue_id": null,
 "ts": "2026-09-06T11:20:00Z"}
```

| field | meaning |
|---|---|
| `id` | unique, stable; the architect records the ids it applied |
| `lever` | `prompt` \| `tools` \| `memory` \| `orchestration` \| `routing` (`contracts.events.Lever`) |
| `trigger` | the *condition* under which the lesson applies, written so another domain can match on it |
| `lesson` | the actionable instruction |
| `domain_tags` | coarse tags for matching (`classification`, `extraction`, `triage`, ...) — **not** the source domain id, so it transfers |
| `source_agent_id` | the agent the lesson was distilled from |
| `source_issue_id` | set when the lesson came from a human-filed issue |
| `ts` | ISO8601 UTC |

## Rules

1. A lesson is recorded **only from an accepted fix** (or a human issue that led
   to one). Never from a proposal, never from an agent's self-report (rule §2.8).
   Recording emits `lesson_recorded`.
2. Lessons are **domain-transferable**: phrase the `trigger` and `lesson` so they
   read sensibly in a domain that does not exist yet. A lesson that names a
   specific label, file path or ticket category belongs in agent *memory*, not
   the playbook.
3. When `use_playbook=true`, the architect reads the **whole** file (it is small,
   no retrieval), applies the relevant lessons, and records the applied ids in
   `agent_created.applied_lessons[]`. When `use_playbook=false` it must not read
   the file at all — that is what makes the **ablation** (playbook-on vs
   playbook-off v0 on Domain B) a fair comparison.
4. The file is append-only in practice. Superseding a lesson means appending a
   new one; do not rewrite history.
5. `GET /playbook` returns the parsed lines as-is.

## Ablation

The Domain B ablation writes `reports/ablation.json`, surfaced by
`GET /insights/compare`. It compares v0 pass rate (mean ± std over
`EVAL_REPEATS`) with `use_playbook=false` against `use_playbook=true`, same
evaluator, same models. A flat or negative result is reported as-is (rule §2.4).
