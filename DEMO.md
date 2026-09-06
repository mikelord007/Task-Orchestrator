# Demo script

Order and timing per `PLAN_ADDENDUM.md` §N (~3:05 total; trim shot 5 first if
running long). Setup commands and env vars: `README.md`. All URLs assume
`frontend` on `http://localhost:3000` and `backend` on `http://localhost:8000`
(`NEXT_PUBLIC_API_URL` default).

**Fill in before recording, once real data exists:** `<AGENT_ID>` (the
`github_triage` agent's id from `/agents`), `<CASE_1>`/`<CASE_2>`/`<CASE_3>` (the
three compare cases, see the pre-recording checklist), `<REJECTED_VERSION>` and
`<DEMOTED_RULE_ID>`. Do not record with the placeholders visible — replace them
with the real ids `scripts/demo_run.py` produces (`reports/summary.md`).

## Pre-recording checklist

Run this once, in order, before you record anything:

- [ ] Both servers up (`make dev` / `pwsh scripts/dev.ps1`); `curl :8000/healthz` OK.
- [ ] `.env` has `LLM_API_KEY` and `GITHUB_TOKEN` set (or `fixtures/github_cache/`
      already populated — the eval run must not hit the live network).
- [ ] `scripts/demo_run.py` (`make demo`) has been run to completion: `github_triage`
      v0 → v6 with one filed-and-fixed human issue, `ticket_triage` v0 → v4, and the
      playbook ablation. `reports/summary.md`, `reports/domain_a.json`,
      `reports/domain_b.json`, `reports/ablation.json` all exist.
- [ ] Note the `github_triage` agent id → `<AGENT_ID>` above.
- [ ] On `/agents/<AGENT_ID>/compare`, pick the three task ids where v0 is wrong and
      the current version is right and the fixing rule is obvious → `<CASE_1..3>`.
- [ ] On `/agents/<AGENT_ID>?tab=fixes`, find one **accepted** memory-lever fix card
      to open (shot 3) and one **rejected** fix card (shot 6).
- [ ] On `/agents/<AGENT_ID>?tab=memory`, find one **demoted** rule (`misses > hits`
      after ≥4 uses) → `<DEMOTED_RULE_ID>`.
- [ ] Confirm holdout has been run at least once for `github_triage` (Runs tab has a
      `holdout` row) and `reports/ablation.json` exists for the Domain B ablation.
- [ ] AO board open in a second window/tab, `BUILD_LOG.md` open in an editor tab.
- [ ] If the live UI misbehaves mid-recording: every shot below has a JSON fallback
      under `reports/` — rehearse pulling those up once so the cut isn't the first
      time you've done it.

---

### 1. (20s) The agent, its tools, its empty memory

**URL:** `/agents` → open the `github_triage` agent → `/agents/<AGENT_ID>?tab=tools`,
then `?tab=memory`, then `?tab=runs` on the **v0** run.

**Clicks:** From `/agents`, click the `github_triage` row. On the agent page, click
the **tools** tab — point at the four `github_*` tools. Click **memory** — it's
empty (or near-empty) at v0. Use the version switcher to select **v0**, click
**runs**, open one task's transcript link for a wrong answer.

**Say:** "This is one agent with real GitHub API access — four tools, cache-backed
so the eval is deterministic — and at v0 its memory is empty. Watch this task: it
gets the labels wrong and makes nine tool calls finding that out."

**Must be visible:** the four tool names + descriptions; the empty/near-empty
memory tab; the v0 transcript's tool-call count (9) and wrong output.

**Fallback:** `runs/<run_id>/<case_id>.t0.json` for that v0 task, opened directly —
point at `tool_calls: 9` and `final_output` vs. `reports/domain_a.json`'s recorded
expected answer.

---

### 2. (30s) Reflection writes rules and a tool note from tool data

**URL:** `/agents/<AGENT_ID>?tab=fixes` → the memory-lever fix card just after v0.

**Clicks:** Open the first `memory`-lever fix card in the timeline. Expand it.

**Say:** "After that run, the agent reflects on its own transcript and the grader's
verdict — never asked if it succeeded — and proposes three rules and a tool note,
each with the issue numbers that are its evidence."

**Must be visible:** the lever chip (`memory`), the hypothesis text, and the list of
memory entries added (not a text diff) with their `evidence_case_ids`.

**Fallback:** `agents/<AGENT_ID>/v1/memory/rules.jsonl` and `tool_notes.jsonl`
opened directly, or the matching `memory_written` events via
`GET /events?agent_id=<AGENT_ID>&kind=memory_written`.

---

### 3. (25s) Gate accepts; the band moves up; the fix card shows the entries

**URL:** same fix card as shot 2, plus `/insights?agent_id=<AGENT_ID>`.

**Clicks:** Scroll the fix card to its before → after numbers (`pass@1`/`pass^k`
mean ± std). Switch to `/insights`, point at **Pass rate by version** — the step up
at this version, with the `fix_accepted` marker.

**Say:** "The gate re-runs the full train set at three trials, checks nothing that
was stably passing regressed, and accepts — the band moves up, and the marker on
the chart is this exact fix."

**Must be visible:** the accepted status pill; before/after `pass@1` and `pass^k`
with ± spread; the corresponding step in the Pass rate chart with its hover marker.

**Fallback:** `reports/domain_a.json`'s per-version `pass_at_1`/`pass_pow_k` series.

---

### 4. (25s) Compare page: the same issue at v0 vs current

**URL:** `/agents/<AGENT_ID>/compare?case_id=<CASE_1>`.

**Clicks:** Land directly on the compare page for `<CASE_1>`. Point at the `v0`
column (wrong labels, high tool-call count) vs. the `current` column (correct
labels, fewer tool calls) and the memory entries injected in each column.

**Say:** "Same task, same expected answer. At v0 it's wrong and makes nine tool
calls. Now: right labels, four tool calls — because these rules fired."

**Must be visible:** both columns' `output`, the `rules_injected` list per column,
and the `tool_calls` count per column, side by side.

**Fallback:** `GET /agents/<AGENT_ID>/compare?case_id=<CASE_1>` JSON directly (or
the two transcripts `runs/<run_id_v0>/<CASE_1>.t0.json` vs.
`runs/<run_id_current>/<CASE_1>.t0.json`).

---

### 5. (25s, trim first if short on time) Insights: band, memory growth, tool efficiency

**URL:** `/insights?agent_id=<AGENT_ID>`.

**Clicks:** Scroll through **Pass rate by version** (already shown in shot 3, don't
re-linger), **Memory growth**, **Tool-usage efficiency**, **Cost, latency and
pass@1-vs-cost**.

**Say:** "All four move together: pass rate up, memory growing — rules and tool
notes per version, demotions marked — and tool calls, errors and cost per task all
falling. This is the cost/speed answer and the memory-growth answer on one screen."

**Must be visible:** memory growth chart's rule/tool-note counts climbing per
version; tool-usage efficiency chart's calls/errors/tokens trending down; the
cost-per-run or pass-vs-cost view.

**Fallback:** `reports/summary.md`'s headline numbers table.

---

### 6. (20s) A rejected fix and a demoted rule

**URL:** `/agents/<AGENT_ID>?tab=fixes` (the rejected card, version `<REJECTED_VERSION>`)
then `/agents/<AGENT_ID>?tab=memory` (rule `<DEMOTED_RULE_ID>`).

**Clicks:** Open the rejected fix card — point at the **rejected** status pill and
the `regressed_case_ids` list. Switch to the memory tab, scroll to
`<DEMOTED_RULE_ID>` — point at `hits`/`misses` and `demoted: true`.

**Say:** "Not every proposal survives the gate — this one regressed a task that was
already stably passing, so it's rejected, on disk, never shipped. And memory
corrects itself too: this rule missed more than it hit, so it's demoted — kept for
the record, no longer injected."

**Must be visible:** the rejected card's regressed case ids; the demoted rule's
`hits`/`misses` counts and its demoted marker.

**Fallback:** the `fix_rejected` event's `regressed_case_ids` via
`GET /events?agent_id=<AGENT_ID>&kind=fix_rejected`; the rule's raw line in
`agents/<AGENT_ID>/v<N>/memory/rules.jsonl` (`"demoted": true`).

---

### 7. (20s) Holdout applies context in later runs; then Domain B's ablation

**URL:** `/agents/<AGENT_ID>?tab=runs` (holdout row) then `/insights` →
**Domain comparison** panel.

**Clicks:** On the Runs tab, filter/scroll to the **holdout** run, point at its
`pass_at_1`/`pass_pow_k`. Switch to Insights' Domain comparison panel — point at the
`ticket_triage` band and the ablation numbers (`use_playbook=false` vs. `true`).

**Say:** "Holdout is the newest issues — filed after everything the agent's memory
knows — and it still gets them right: that's applying learned context in later
runs, not memorizing. And it's not one-agent luck: `ticket_triage` is a second,
unrelated domain, and starting it with the playbook on beats starting it cold."

**Must be visible:** the holdout row's pass rate; the Domain comparison panel with
both domains' bands and the ablation's two v0 numbers.

**Fallback:** `reports/domain_a.json`'s holdout section; `reports/ablation.json`
directly (`use_playbook: false` vs. `true` pass rates).

---

### 8. (10s) AO board + BUILD_LOG.md + repo

**URL/window:** AO board (session list) + `BUILD_LOG.md` open in an editor.

**Clicks:** Show the AO board with every worker session; scroll `BUILD_LOG.md`'s
sessions table.

**Say:** "Built by one orchestrator session and one worker session per
workstream — every branch, every PR, every outcome is in this log." State the repo
URL.

**Must be visible:** the AO session list; `BUILD_LOG.md`'s sessions table with PR
links.

**Fallback:** none needed — this shot has no live-UI dependency.
