"""Generate the `ticket_triage` corpus: 50 synthetic support tickets.

Everything here is invented. No real customer data is copied, quoted or
paraphrased. Two sources:

* ``HARD_CASES`` - hand-written tickets, one per hard-case type, where the
  interesting judgement lives (sarcasm, buried p0, anger that must not inflate
  priority, ...). These are authored text, not generated.
* ``_routine_cases()`` - templated everyday tickets combined with a fixed seed
  (``SEED``) so the corpus is byte-for-byte reproducible.

    python scripts/build_ticket_cases.py

Outputs
-------
fixtures/tickets/<ticket_id>.json        one file per ticket (source of truth)
evaluators/ticket_triage/cases.jsonl     the evaluator cases

THE LABELLING POLICY BELOW IS DELIBERATELY NOT IN THE EVALUATOR README. The
README describes the fields and what "good" means; the exact decision table is
what the agent has to *learn* from its train failures, which is the whole point
of the improvement loop. Keep it here.

Category
    billing   invoices, charges, refunds, pricing, plan/subscription payment
    bug       something is broken: errors, crashes, wrong output, data loss
    feature   a request for a capability that does not exist yet
    account   sign-in, SSO, passwords, seats, permissions, account deletion
    other     questions, docs, praise, anything with no actionable defect

Priority (business impact only - never tone)
    p0  outage, data loss, security/privacy incident, everyone blocked,
        money moved wrongly at scale
    p1  no workaround and core work is blocked for the customer
    p2  real defect with a workaround, or a single-account problem
    p3  feature requests, questions, cosmetic issues, praise
    Enterprise tier bumps one step (p3->p2, p2->p1) but never reaches p0
    on tier alone.
    A ticket carrying several issues takes the category and priority of its
    most severe issue.

needs_human (does a human have to touch this before it is answered?)
    True when: priority is p0 or p1; or a refund/chargeback/dispute is asked
    for; or security, legal, privacy or account deletion is involved; or the
    customer is angry / threatening to leave / demanding a manager; or the
    ticket bundles several issues and has to be split.
    Anger sets needs_human. Anger does NOT set priority.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "tickets"
CASES_PATH = REPO_ROOT / "evaluators" / "ticket_triage" / "cases.jsonl"

SEED = 20260906
TRAIN_FRACTION = 0.7
TOTAL = 50

# --------------------------------------------------------------------- hard cases
# Hand-authored. `tags` here carry only the hard-case type; the derived
# cat:/prio:/tier: tags are added later for every ticket.

HARD_CASES: list[dict] = [
    # ---------------------------------------------------------------- sarcasm
    {
        "subject": "Fantastic work on the export feature",
        "body": (
            "Really, congratulations. Truly outstanding engineering. I clicked "
            "Export on our 40k-row workspace and it produced a 0-byte file, and "
            "then the workspace came back empty. Every board, gone. I especially "
            "enjoyed that there is no undo. Chef's kiss. Anyway, our whole ops "
            "team is sitting here staring at an empty screen, so whenever you get "
            "a spare moment."
        ),
        "customer_tier": "pro",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["sarcasm"],
    },
    {
        "subject": "Love the new pricing page, very transparent",
        "body": (
            "What a delightful surprise to discover that the plan I have been on "
            "for eleven months quietly became $80 more per seat. No email, no "
            "banner, nothing. Beautiful. I'd like the difference back on the last "
            "invoice please, and an explanation I can forward to finance."
        ),
        "customer_tier": "free",
        "expected": {"category": "billing", "priority": "p2", "needs_human": True},
        "tags": ["sarcasm"],
    },
    {
        "subject": "10/10 would lock myself out again",
        "body": (
            "Genuinely impressive that rotating my own password logs out every "
            "member of my org and invalidates their SSO sessions. I've had four "
            "people ping me in the last ten minutes. None of them can get in. "
            "No idea how to undo it from the admin panel, there's no button. "
            "Great feature."
        ),
        "customer_tier": "enterprise",
        "expected": {"category": "account", "priority": "p1", "needs_human": True},
        "tags": ["sarcasm"],
    },
    {
        "subject": "Wonderful colour choice on the delete button",
        "body": (
            "Whoever picked the exact same grey for Cancel and Delete Permanently "
            "deserves a raise. I have not lost anything yet, purely by luck. Could "
            "you perhaps make destructive actions look destructive? Radical idea, "
            "I know."
        ),
        "customer_tier": "pro",
        "expected": {"category": "feature", "priority": "p3", "needs_human": False},
        "tags": ["sarcasm"],
    },
    {
        "subject": "Superb documentation, no notes",
        "body": (
            "The API reference says the webhook retries 'a few times'. A few. I "
            "have built a reconciliation job around that sentence. Could someone "
            "who knows the actual number write it down? I'm not blocked, I just "
            "enjoy guessing."
        ),
        "customer_tier": "free",
        "expected": {"category": "other", "priority": "p3", "needs_human": False},
        "tags": ["sarcasm"],
    },
    # ------------------------------------------------------------- mixed-language
    {
        "subject": "No puedo iniciar sesion desde ayer",
        "body": (
            "Hola, buenas tardes. Since yesterday afternoon I cannot sign in with "
            "my work email. El sistema dice 'invalid credentials' pero la "
            "contrasena es correcta, la acabo de restablecer dos veces. My "
            "colleagues on the same domain can log in fine, so parece que es solo "
            "mi cuenta. Gracias de antemano."
        ),
        "customer_tier": "pro",
        "expected": {"category": "account", "priority": "p2", "needs_human": False},
        "tags": ["mixed-language"],
    },
    {
        "subject": "Rechnung stimmt nicht / invoice mismatch",
        "body": (
            "Guten Tag, wir wurden diesen Monat zweimal belastet. The invoice "
            "INV-40122 shows 24 seats but we only have 12 aktive Nutzer. Bitte um "
            "Rueckerstattung der Differenz und eine korrigierte Rechnung fuer "
            "unsere Buchhaltung. Vielen Dank."
        ),
        "customer_tier": "pro",
        "expected": {"category": "billing", "priority": "p2", "needs_human": True},
        "tags": ["mixed-language"],
    },
    {
        "subject": "Aplicacion se cierra al exportar - production down",
        "body": (
            "Urgente. La aplicacion se cierra sola cada vez que exportamos el "
            "reporte diario, and this has been happening on every machine in the "
            "office since the update this morning. Nadie puede generar reportes. "
            "We have no workaround at all, todo el equipo esta detenido. Somos "
            "clientes enterprise, necesitamos ayuda ya."
        ),
        "customer_tier": "enterprise",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["mixed-language"],
    },
    {
        "subject": "Feature request: format de date francais",
        "body": (
            "Bonjour, serait-il possible d'ajouter le format JJ/MM/AAAA dans les "
            "parametres? Our French team keeps misreading American dates in the "
            "reports. Ce n'est pas urgent du tout, juste agreable a avoir. Merci "
            "beaucoup pour votre travail."
        ),
        "customer_tier": "pro",
        "expected": {"category": "feature", "priority": "p3", "needs_human": False},
        "tags": ["mixed-language"],
    },
    {
        "subject": "Doubt about API rate limit / duda sobre limites",
        "body": (
            "Hi team, quick question, nada urgente. The docs mention a limit of "
            "1000 requests per minute, pero no dice si es por token o por "
            "organizacion. We are planning our integration and want to size it "
            "correctly. Podrian aclarar? Gracias."
        ),
        "customer_tier": "free",
        "expected": {"category": "other", "priority": "p3", "needs_human": False},
        "tags": ["mixed-language"],
    },
    # ---------------------------------------------------------------- multi-issue
    {
        "subject": "Three things",
        "body": (
            "1. The keyboard shortcut for search stopped working on Firefox. Minor, "
            "I use the mouse.\n"
            "2. Would love a dark mode for the print view someday.\n"
            "3. Also our nightly sync has been silently dropping about 15% of "
            "records for the past four days and we only noticed because finance "
            "caught a mismatch. We have no way to tell which records were lost.\n"
            "Sorry to cram these together."
        ),
        "customer_tier": "pro",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["multi-issue", "buried-p0"],
    },
    {
        "subject": "Couple of issues from onboarding",
        "body": (
            "First, the invite email lands in spam for everyone on our domain, so "
            "half the team never onboarded. Second, we were charged for 30 seats "
            "on the first invoice when we only invited 18. Third, the profile "
            "photo upload rejects PNGs over 2MB with no error message. Happy to "
            "split this into separate tickets if that's easier."
        ),
        "customer_tier": "pro",
        "expected": {"category": "billing", "priority": "p2", "needs_human": True},
        "tags": ["multi-issue"],
    },
    {
        "subject": "Bug + question + idea",
        "body": (
            "Bug: the CSV importer maps the second and third columns the wrong way "
            "round. We can fix it by reordering the file before upload, so it's "
            "annoying rather than fatal.\n"
            "Question: does the importer support tab-separated files?\n"
            "Idea: an import preview screen would have saved us two hours today."
        ),
        "customer_tier": "free",
        "expected": {"category": "bug", "priority": "p2", "needs_human": True},
        "tags": ["multi-issue"],
    },
    {
        "subject": "Several problems since Tuesday",
        "body": (
            "Our SSO connection drops people back to the login screen roughly "
            "every twenty minutes and they have to re-authenticate; nobody can "
            "hold a session long enough to finish a report, and there is no "
            "workaround we can find. Separately, the docs link in the footer 404s. "
            "Separately again, we would like an export to Parquet eventually."
        ),
        "customer_tier": "pro",
        "expected": {"category": "account", "priority": "p1", "needs_human": True},
        "tags": ["multi-issue"],
    },
    {
        "subject": "Two small things and one not so small",
        "body": (
            "Small: the tooltip on the archive icon is cut off at 125% zoom.\n"
            "Small: 'Recieve notifications' is spelled wrong in settings.\n"
            "Not so small: any user with the Viewer role can open the billing page "
            "and read our card details and full invoice history. I checked with two "
            "different accounts. That seems bad."
        ),
        "customer_tier": "pro",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["multi-issue", "buried-p0"],
    },
    # ------------------------------------------------------------------ buried-p0
    {
        "subject": "Question about the reporting filters",
        "body": (
            "Hi, I wanted to ask how the date filter on the reports page treats "
            "timezones. We are in UTC+5:30 and I want to be sure the daily figures "
            "line up with our accounting day. I read the help article twice and it "
            "does not really say. It would be helpful if the docs spelled it out, "
            "or if the filter showed the timezone next to the dates. Not a big deal "
            "either way, we can work around it with a spreadsheet for now. On an "
            "unrelated note, the report export we downloaded this morning contains "
            "rows belonging to a different company. Names, email addresses, deal "
            "values, none of it ours. I stopped opening it once I realised. Anyway, "
            "mainly writing about the timezone thing."
        ),
        "customer_tier": "pro",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["buried-p0"],
    },
    {
        "subject": "Minor UI polish suggestions",
        "body": (
            "A short list of nits from our design team after a week of use:\n"
            "- the sidebar collapse animation stutters on Safari\n"
            "- the empty state illustration is off-centre on tablet\n"
            "- table headers lose their border when you scroll horizontally\n"
            "- the avatar stack overlaps oddly at exactly five members\n"
            "None of these block anyone, they are just papercuts we noticed. "
            "Also, since about 09:00 today nobody in our organisation can load the "
            "app at all - it hangs on the loading spinner forever on every browser "
            "and every machine we have tried. Probably related to the same release?"
        ),
        "customer_tier": "pro",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["buried-p0", "long-body"],
    },
    {
        "subject": "Thanks for the quick fix last week",
        "body": (
            "Just wanted to say the team really appreciated how fast you turned "
            "around the timezone bug, it made our month-end much less painful and "
            "I've passed that on internally. While I have you: is there a roadmap "
            "page we can subscribe to? We would like to plan around the Q4 "
            "features. Oh and one more thing, our API token from the integration "
            "guide appears to have been printed in plain text in the shared audit "
            "log that all 200 of our users can read. Probably worth a look."
        ),
        "customer_tier": "enterprise",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["buried-p0"],
    },
    {
        "subject": "Feedback after our first month",
        "body": (
            "Overall a good month. Onboarding was smooth, the import tool saved us "
            "a lot of manual work, and support has been responsive. A few wishes: "
            "bulk edit on the boards view, a Slack integration that posts on status "
            "change, and keyboard navigation in the picker. I know these are all "
            "nice-to-haves.\n\n"
            "One thing I should mention: deleting a single project deleted every "
            "project in the workspace for us on Friday. We restored from our own "
            "backup so we are fine, but we have not touched Delete since."
        ),
        "customer_tier": "free",
        "expected": {"category": "bug", "priority": "p0", "needs_human": True},
        "tags": ["buried-p0", "long-body"],
    },
    # --------------------------------------------------------- angry-low-priority
    {
        "subject": "ABSOLUTELY UNACCEPTABLE",
        "body": (
            "I have been asking for a dark mode for EIGHT MONTHS. Eight. Every "
            "other tool we use has it. I have raised it three times and been "
            "fobbed off every time. If this is not on the roadmap by the end of "
            "the quarter we are moving to a competitor and I will make sure our "
            "partners hear about it. Put me through to whoever actually makes "
            "decisions there."
        ),
        "customer_tier": "pro",
        "expected": {"category": "feature", "priority": "p3", "needs_human": True},
        "tags": ["angry-low-priority"],
    },
    {
        "subject": "This is a joke of a product",
        "body": (
            "The font in the settings panel is TOO SMALL. I have complained about "
            "this before. I am not going to squint at my screen because your "
            "designers like whitespace. I want a manager. I want a date. I have "
            "been a customer for three years and this is how you treat people."
        ),
        "customer_tier": "free",
        "expected": {"category": "feature", "priority": "p3", "needs_human": True},
        "tags": ["angry-low-priority"],
    },
    {
        "subject": "Cancel our contract",
        "body": (
            "Done with this. The export button is in a stupid place, I have to "
            "click twice to get to it, and nobody has ever listened to a word I "
            "have said about the layout. Everything still works, I just cannot "
            "stand using it. Send me whoever handles renewals because we are not "
            "signing again."
        ),
        "customer_tier": "enterprise",
        "expected": {"category": "feature", "priority": "p2", "needs_human": True},
        "tags": ["angry-low-priority"],
    },
    {
        "subject": "Why is this so hard",
        "body": (
            "WHERE is the setting to change the default sort order. I have looked "
            "everywhere. Your help centre is useless, your search is useless. I "
            "have wasted twenty minutes of my life on this. Someone tell me where "
            "the button is or admit there isn't one."
        ),
        "customer_tier": "pro",
        "expected": {"category": "other", "priority": "p3", "needs_human": True},
        "tags": ["angry-low-priority"],
    },
    {
        "subject": "Escalating this immediately",
        "body": (
            "URGENT. CRITICAL. Your release notes email went out with our company "
            "name misspelled. This is deeply unprofessional and reflects badly on "
            "us internally. I want this acknowledged today by someone senior and I "
            "want to know what process failed. I am copying my VP on the next one."
        ),
        "customer_tier": "enterprise",
        "expected": {"category": "other", "priority": "p2", "needs_human": True},
        "tags": ["angry-low-priority"],
    },
]


# ------------------------------------------------------------------ routine cases
# Templated everyday traffic. Slots are filled from a seeded RNG so the corpus is
# reproducible; the (category, priority, needs_human) triple is fixed per template
# and follows the same policy as the hard cases.

ROUTINE_TEMPLATES: list[dict] = [
    {
        "subject": "Invoice {inv} does not match our seat count",
        "body": (
            "Our latest invoice {inv} bills {billed} seats but the admin panel "
            "shows {actual} active users. Could you check what happened and send a "
            "corrected copy? Nothing is blocked, we just need the numbers to line "
            "up before {month} close."
        ),
        "expected": {"category": "billing", "priority": "p2", "needs_human": False},
    },
    {
        "subject": "Refund request for duplicate charge",
        "body": (
            "We were charged twice on {date} for the same subscription, both for "
            "${amount}. The bank shows two identical transactions. Please refund "
            "one of them. Reference {inv} if that helps."
        ),
        "expected": {"category": "billing", "priority": "p2", "needs_human": True},
    },
    {
        "subject": "How do I switch from monthly to annual billing?",
        "body": (
            "We would like to move our {actual}-seat plan to annual billing before "
            "{month}. I cannot find the option in the billing settings, only the "
            "card details. Is this something you have to do on your side?"
        ),
        "expected": {"category": "billing", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "All payments failing since {date}",
        "body": (
            "Every card charge across our organisation has been declining since "
            "{date} with 'processor error'. This affects all {actual} of our "
            "billing accounts, not just one card, and our customers are seeing it "
            "too. Nothing we do on our side changes it."
        ),
        "expected": {"category": "billing", "priority": "p0", "needs_human": True},
    },
    {
        "subject": "Error {code} when saving a {thing}",
        "body": (
            "Whenever I edit a {thing} and hit save, I get error {code} and the "
            "change is lost. It happens on Chrome and Edge. Reloading and saving "
            "again usually works on the second try, so I can get by, but it is "
            "slowing the team down."
        ),
        "expected": {"category": "bug", "priority": "p2", "needs_human": False},
    },
    {
        "subject": "{thing} view will not load at all",
        "body": (
            "Since {date} the {thing} view spins forever and eventually shows "
            "error {code}. This is the screen the whole team works in and we have "
            "not found any way around it - different browsers, incognito, cleared "
            "cache, nothing helps. Nobody here can do their job."
        ),
        "expected": {"category": "bug", "priority": "p1", "needs_human": True},
    },
    {
        "subject": "Wrong totals in the {thing} summary",
        "body": (
            "The summary at the top of the {thing} page adds up to ${amount} but "
            "the rows below it total something different. Exporting to CSV gives "
            "the correct figure, so we are using that for now. Started around "
            "{date}."
        ),
        "expected": {"category": "bug", "priority": "p2", "needs_human": False},
    },
    {
        "subject": "Typo in the {thing} confirmation dialog",
        "body": (
            "Tiny thing: the confirmation dialog for a {thing} says 'are you sure "
            "you want to delete this items'. Should be 'this item'. Not urgent at "
            "all, just noticed it while testing."
        ),
        "expected": {"category": "bug", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Cannot sign in after password reset",
        "body": (
            "I reset my password on {date} and now neither the old nor the new one "
            "works. The reset email arrives fine and the link says success, but "
            "logging in returns 'invalid credentials'. My colleagues are not "
            "affected."
        ),
        "expected": {"category": "account", "priority": "p2", "needs_human": False},
    },
    {
        "subject": "SSO login loop for our whole organisation",
        "body": (
            "Since {date} every user in our org is bounced straight back to the "
            "login page after authenticating with our identity provider. All "
            "{actual} people are locked out and there is no fallback login we can "
            "use. Nothing changed on our IdP side."
        ),
        "expected": {"category": "account", "priority": "p0", "needs_human": True},
    },
    {
        "subject": "Please add {count} more seats",
        "body": (
            "We are onboarding {count} people next week and the admin panel says "
            "we are at our seat limit. Can you raise it, and confirm what that does "
            "to invoice {inv}? Not blocking anyone yet."
        ),
        "expected": {"category": "account", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Delete our account and all associated data",
        "body": (
            "We are winding down this workspace. Please delete the account and all "
            "stored data permanently and confirm in writing once it is done, as we "
            "need the record for our own compliance file. Final invoice was {inv}."
        ),
        "expected": {"category": "account", "priority": "p2", "needs_human": True},
    },
    {
        "subject": "Feature request: export {thing} to {format}",
        "body": (
            "It would help a lot if we could export a {thing} directly to "
            "{format}. Right now we copy into a spreadsheet by hand every {month}. "
            "Definitely a nice-to-have, not blocking us."
        ),
        "expected": {"category": "feature", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Any plans for a {thing} API?",
        "body": (
            "Is a public API for {thing} objects on the roadmap? We would like to "
            "sync them into our warehouse nightly instead of exporting to {format} "
            "by hand. No rush, planning ahead."
        ),
        "expected": {"category": "feature", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Bulk edit for {thing} records",
        "body": (
            "Editing {count} {thing} records one at a time takes most of an "
            "afternoon. A multi-select with a bulk edit action would save us that "
            "time every {month}. Would you consider it?"
        ),
        "expected": {"category": "feature", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Question about the {thing} retention window",
        "body": (
            "How long are deleted {thing} records kept before they are purged? The "
            "help centre says 'a limited period'. We need a number for an internal "
            "policy document. Thanks."
        ),
        "expected": {"category": "other", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Thanks for the {thing} improvements",
        "body": (
            "Nothing broken here, just wanted to say the {thing} changes shipped "
            "around {date} made a real difference to our {month} reporting. Please "
            "pass it on to the team."
        ),
        "expected": {"category": "other", "priority": "p3", "needs_human": False},
    },
    {
        "subject": "Where can I find the {format} import guide?",
        "body": (
            "I remember a guide about importing {format} files into {thing} "
            "records but I cannot find it any more - the link I had bookmarked "
            "returns error {code}. Could you point me to the current one?"
        ),
        "expected": {"category": "other", "priority": "p3", "needs_human": False},
    },
]

SLOTS = {
    "inv": [f"INV-{n}" for n in range(40100, 40140)],
    "billed": [18, 24, 30, 36, 45, 60],
    "actual": [8, 12, 15, 22, 27, 33],
    "count": [3, 5, 8, 12, 20],
    "amount": ["149.00", "480.00", "1,240.00", "2,600.00", "89.00"],
    "date": ["3 March", "17 April", "2 May", "28 May", "11 June", "9 July"],
    "month": ["quarter", "month", "sprint", "financial year"],
    "thing": ["board", "report", "workspace", "dashboard", "project", "contact"],
    "code": ["E-4021", "E-500", "HTTP 502", "E-1109", "HTTP 403"],
    "format": ["CSV", "Parquet", "XLSX", "JSON"],
}

TIERS = ["free", "pro", "enterprise"]
TIER_WEIGHTS = [4, 5, 2]

BUMP = {"p3": "p2", "p2": "p1", "p1": "p1", "p0": "p0"}


def _apply_tier(expected: dict, tier: str) -> dict:
    """Enterprise raises priority one step (never to p0) and, at p1, a human."""
    out = dict(expected)
    if tier == "enterprise":
        out["priority"] = BUMP[out["priority"]]
    if out["priority"] in ("p0", "p1"):
        out["needs_human"] = True
    return out


def _routine_cases(rng: random.Random, n: int) -> list[dict]:
    cases = []
    order = list(range(len(ROUTINE_TEMPLATES)))
    rng.shuffle(order)
    for i in range(n):
        template = ROUTINE_TEMPLATES[order[i % len(order)]]
        slots = {key: rng.choice(values) for key, values in SLOTS.items()}
        tier = rng.choices(TIERS, weights=TIER_WEIGHTS, k=1)[0]
        cases.append(
            {
                "subject": template["subject"].format(**slots),
                "body": template["body"].format(**slots),
                "customer_tier": tier,
                "expected": _apply_tier(template["expected"], tier),
                "tags": ["routine"],
            }
        )
    return cases


# ----------------------------------------------------------------------- assembly


def derived_tags(case: dict) -> list[str]:
    expected = case["expected"]
    tags = list(case["tags"])
    tags.append(f"cat:{expected['category']}")
    tags.append(f"prio:{expected['priority']}")
    tags.append(f"tier:{case['customer_tier']}")
    if expected["needs_human"]:
        tags.append("needs-human")
    if len(case["body"]) > 900 and "long-body" not in tags:
        tags.append("long-body")
    return sorted(dict.fromkeys(tags))


def build_all() -> list[dict]:
    rng = random.Random(SEED)
    # HARD_CASES already carry their final expected triple - they were authored
    # with the customer's tier in hand, so `_apply_tier` must not run over them.
    raw = [dict(c) for c in HARD_CASES]
    raw += _routine_cases(rng, TOTAL - len(HARD_CASES))

    cases = []
    for index, case in enumerate(raw, start=1):
        ticket_id = f"tk-{index:03d}"
        cases.append(
            {
                "id": ticket_id,
                "split": "train",  # rewritten by the stratified split
                "input": {
                    "ticket_id": ticket_id,
                    "subject": case["subject"],
                    "body": case["body"],
                    "customer_tier": case["customer_tier"],
                },
                "expected": case["expected"],
                "tags": derived_tags(case),
            }
        )
    return cases


HARD_TAGS = ("buried-p0", "sarcasm", "angry-low-priority", "multi-issue", "mixed-language")


def stratum(case: dict) -> str:
    """The hard-case type a ticket belongs to, else `routine`."""
    for tag in HARD_TAGS:
        if tag in case["tags"]:
            return tag
    return "routine"


def apply_stratified_split(cases: list[dict]) -> list[dict]:
    """70/30 train/holdout inside every stratum, deterministically by id."""
    groups: dict[str, list[dict]] = {}
    for case in cases:
        groups.setdefault(stratum(case), []).append(case)
    for members in groups.values():
        members.sort(key=lambda c: c["id"])
        cut = round(len(members) * TRAIN_FRACTION)
        for idx, case in enumerate(members):
            case["split"] = "train" if idx < cut else "holdout"
    return sorted(cases, key=lambda c: c["id"])


def main(argv: list[str] | None = None) -> int:
    cases = apply_stratified_split(build_all())

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in FIXTURE_DIR.glob("tk-*.json"):
        stale.unlink()
    for case in cases:
        path = FIXTURE_DIR / f"{case['id']}.json"
        path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CASES_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(case, sort_keys=True) + "\n")

    train = sum(1 for c in cases if c["split"] == "train")
    print(f"Wrote {len(cases)} tickets ({train} train / {len(cases) - train} holdout)")
    counts: dict[str, int] = {}
    for case in cases:
        counts[stratum(case)] = counts.get(stratum(case), 0) + 1
    print(f"Strata: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
