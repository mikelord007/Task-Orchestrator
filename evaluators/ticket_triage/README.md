# `ticket_triage`

Triage an inbound customer support ticket: what is it about, how urgent is it,
and does a human have to touch it before it is answered.

50 tickets, all **synthetic**. Nothing here is copied, quoted or paraphrased from
real customer data. 24 are hand-authored hard cases; the other 26 are templated
everyday traffic generated from a fixed seed. See *Reproducing the corpus* below.

This is the **second domain**, and the target of the playbook ablation: the same
system generates an agent here with and without the lessons learned on
`github_triage`, and the two v0 numbers are compared. It is deliberately a
different shape of problem — no third-party API, no repository conventions to
mine, just judgement over prose.

## The task

**Input** (`cases.jsonl` → `input`):

```json
{
  "ticket_id": "tk-017",
  "subject": "Question about the reporting filters",
  "body": "...",
  "customer_tier": "pro"
}
```

`customer_tier` is one of `free`, `pro`, `enterprise` and is present on every
ticket. It is not decoration — it carries signal.

**Expected output** (`expected`), which is also the JSON shape the agent must produce:

```json
{"category": "bug", "priority": "p1", "needs_human": true}
```

| field | values |
|---|---|
| `category` | `billing` · `bug` · `feature` · `account` · `other` |
| `priority` | `p0` · `p1` · `p2` · `p3` |
| `needs_human` | `true` / `false` |

## What "good" means

**`category`** — what the ticket is *about*:

| | |
|---|---|
| `billing` | invoices, charges, refunds, pricing, plan and subscription payment |
| `bug` | something is broken: errors, crashes, wrong output, data loss |
| `feature` | a request for a capability that does not exist yet |
| `account` | sign-in, SSO, passwords, seats, permissions, account deletion |
| `other` | questions, docs, praise — anything with no actionable defect |

**`priority`** — business impact, and only business impact:

| | |
|---|---|
| `p0` | outage, data loss, security or privacy incident, everyone blocked, money moved wrongly at scale |
| `p1` | no workaround, and core work is blocked for the customer |
| `p2` | a real defect that has a workaround, or a problem confined to one account |
| `p3` | feature requests, questions, cosmetic issues, praise |

**`needs_human`** — would answering this correctly require a person, rather than
an automated reply? Tickets that need a decision, an apology, money moved, or a
judgement call do; routine ones that a templated answer resolves do not.

That is as far as the specification goes on purpose. The rest of the triage
policy — how tier interacts with priority, what a ticket carrying several issues
resolves to, and exactly which signals set `needs_human` — is **not written down
here**. It is consistent and learnable, and learning it from train failures is
what the improvement loop is for. The full policy lives in the generator,
`scripts/build_ticket_cases.py`, which the agent never reads.

### Scoring

`score.py` is deterministic, offline, stdlib-only:

- **`passed`** iff all three fields match.
- **`score`** = fraction of the three that matched — `0.0`, `0.333`, `0.667`, `1.0`.
- Comparison is case- and whitespace-insensitive; `needs_human` also accepts
  `"true"` / `"yes"` / `1` and their negatives.
- A non-dict / missing output scores 0 with `notes = "no_output"`.

`notes` uses a fixed vocabulary so `failure_signature` and the improver's failure
grouping stay stable across runs: `category_mismatch:<expected>-><actual>`,
`priority_mismatch:<expected>-><actual>`, `needs_human_mismatch:<expected>-><actual>`,
`no_output`, `ok` — sorted and `;`-joined. An absent or unparseable field shows as
`missing` on the actual side, which is a different failure from guessing wrong and
groups separately.

**Headroom.** An empty output scores 0.0 on every case and never passes. The best
possible *constant* answer (`bug` / `p0` / `true`) passes 16% and means 0.373 — and
even an agent that got `category` right on all 50 cases still only passes 16%
without the priority and `needs_human` rules. Requiring all three fields, over a
corpus that is nearly half hard cases, leaves a long climb.

## Allowed tools

Offline helpers from `backend/toolbox/` only. There is no external API in this
domain; everything the agent needs is in the ticket text.

| tool | use |
|---|---|
| `regex_extract` | pull invoice numbers, error codes, dates and counts out of the body |
| `json_validate` | check the answer is the three-field object before returning it |

## Hard cases

24 of the 50 are hand-authored to punish a naive reading. Each carries its type as
a tag so failure analysis can group on it.

| tag | n | what it tests |
|---|---|---|
| `buried-p0` | 6 | the severe fact is one line inside an otherwise low-priority ticket — a polite question, a list of UI nits, a thank-you note — and it is never in the subject |
| `sarcasm` | 5 | the tone is warm and the content is a disaster ("Fantastic work on the export feature", followed by data loss) |
| `angry-low-priority` | 5 | shouting, threats to churn, demands for a manager — over a font size or a button position. Anger is a `needs_human` signal, not a priority signal, and a naive agent inflates it to p0 |
| `multi-issue` | 5 | two or three unrelated issues in one ticket, of different severities |
| `mixed-language` | 5 | Spanish, German or French interleaved with English, across every severity level so language never correlates with the answer |

`buried-p0` and `multi-issue` overlap on two tickets, which is realistic: the buried
severe item usually arrives inside a list of small ones.

`tags` additionally carries `cat:<category>`, `prio:<p0..p3>`, `tier:<free|pro|enterprise>`,
`needs-human` where true, `routine` for the 26 templated tickets, and `long-body`
(> 900 chars).

## Corpus at a glance

| | |
|---|---|
| categories | `bug` 16 · `billing` 9 · `feature` 9 · `account` 8 · `other` 8 |
| priorities | `p3` 21 · `p0` 11 · `p2` 11 · `p1` 7 |
| `needs_human` | true 29 · false 21 |
| tiers | `pro` 26 · `free` 16 · `enterprise` 8 |

## Splits — stratified 70/30

36 train / 14 holdout, split **inside each stratum** (the five hard-case types plus
`routine`) so the holdout is not accidentally all easy:

| stratum | train | holdout |
|---|---|---|
| `routine` | 18 | 8 |
| `buried-p0` | 4 | 2 |
| `sarcasm` | 4 | 1 |
| `mixed-language` | 4 | 1 |
| `angry-low-priority` | 4 | 1 |
| `multi-issue` | 2 | 1 |

The split is derived from the ticket id, so it is stable across regenerations.
Holdout is never shown to the improver (PLAN.md §4.3); it is run only for reporting
after a fix is accepted.

## Reproducing the corpus

```bash
python scripts/build_ticket_cases.py
```

Stdlib only, no network, fixed seed (`SEED = 20260906`), idempotent — it rewrites
`fixtures/tickets/tk-*.json` and `cases.jsonl` identically every time. The hard
cases are literal authored text in the script, not generated, so editing one means
editing the script and re-running rather than hand-patching `cases.jsonl`.
`fixtures/tickets/<ticket_id>.json` holds the full case (input, expected, tags,
split) one file per ticket, which is the readable form for reviewing the corpus by
eye and for the demo.
