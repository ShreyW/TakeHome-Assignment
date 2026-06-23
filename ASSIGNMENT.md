# Reconciliation Service — SWE Take-Home

**Time budget: 3 days.** Your clock started when you opened your personal **start link** (that's also
how you received this package). You have **3 days from that moment** to submit, via your **submit
link**. We record start and submit times only — work at whatever pace you like within the window.

## Background

A clinical research **site** runs trials for pharma **sponsors**. The money flows through a chain of
documents, and keeping that chain reconciled — so the site knows what it's owed and what it has
actually been paid — is the job you're being handed.

- A **CTA** (Clinical Trial Agreement) is the contract. Inside is a budget: a grid of **visits** ×
  **procedures** with dollar amounts, plus **site fees** (startup, admin, pharmacy, advertising) and
  rules (holdbacks, caps, screen-failure terms, payment terms).
- During the trial the site logs subject **activities** (visits, procedures, unscheduled events) in a
  **CTMS** (RealTime, CRIO, Clinical Conductor, eClinPro …).
- The site **invoices** the sponsor for those activities. The sponsor (or its CRO / a **payment
  portal**) pays, and sends a **remittance** that says which invoice(s) and line items a payment covers.
- Sometimes a portal **autopays** an activity directly, with no site invoice at all.
- The cash shows up in the network's **bank** feed: one shared Plaid export for the operating account,
  with every sponsor's deposits for every study intermixed (the bank doesn't know about studies).

These documents are messy and live in different systems. **Your task is to make them reconcile.**

## Glossary — every term, defined

You do **not** need any prior clinical-trial knowledge. Everything the rest of this doc uses is defined
here, in plain terms.

**People & organizations**
- **Sponsor** — the pharmaceutical company running and funding the trial. It owes the site money for
  work performed (e.g. Meridian, Vantix, Calyx).
- **CRO (Contract Research Organization)** — a firm the sponsor outsources trial operations and/or
  payments to. Sometimes the CRO, not the sponsor, is who actually pays the site and sends the
  paperwork (e.g. Cordis Clinical).
- **Site** — the clinic/research center that runs the trial and sees patients. **This is "you"** — the
  party whose books you are reconciling. The site bills sponsors and receives payments.
- **Site network** — an organization that operates several sites. Here one network (Atlas Research
  Partners) runs all the sites; each physical site has a number like `ARP-12`.
- **Investigator (PI, Principal Investigator)** — the lead physician responsible for a study at a site.
- **Subject** — a trial participant (a patient). Identified only by an id like `S-12-001`; no personal data.

**The trial**
- **Study / Protocol** — one specific clinical trial. It has a **study code** (e.g. `MRD-204-017`) and a
  **protocol name** (e.g. `HORIZON`); both refer to the same trial.
- **Indication** — the disease the trial targets (context only; not needed to reconcile).

**The contract & the work**
- **CTA (Clinical Trial Agreement)** — the contract between sponsor and site. Contains the budget and
  the billing rules. **Your source of truth for what each unit of work is worth.**
- **Budget / visit×procedure grid** — the table inside the CTA: rows are procedures, columns are visits,
  cells are dollar amounts. Defines what the site may bill for each unit of work.
- **Visit** — a scheduled subject appointment in the protocol (Screening, V1, V2, …), each with a price.
- **Procedure** — a billable task performed at a visit (blood draw, ECG, ultrasound, …).
- **Activity** — one logged unit of work: a given subject's visit/procedure on a given date. This is
  what the CTMS records and what you bill against.
- **Unscheduled visit** — a visit not on the standard schedule (e.g. a repeat lab draw). The CTA may
  allow billing it per-procedure; if the CTA has no provision for it, it isn't billable.
- **Screen failure** — a subject who was screened but never enrolled. Billed under special (capped) CTA rules.
- **Site fee / site cost** — a non-visit charge the site bills (start-up, annual admin, pharmacy
  maintenance, advertising). Not tied to a subject visit.
- **Cap** — a CTA-imposed maximum on a fee (e.g. chart review reimbursed up to $3,000). Billing over the
  cap is an exception.

**Billing & money**
- **Invoice** — a bill the site sends the sponsor/CRO for activities or site costs. Its **face amount**
  is the total printed on it (what "paid at 90% of face" refers to).
- **Payment** — money the sponsor/CRO sends to the site. May arrive as an **ACH** transfer, a **wire**,
  or a **card** payment; one payment can cover several invoices.
- **Remittance (remittance advice)** — the document returned with/after a payment listing which
  invoice(s) and line items that payment covers. The bridge from a lump payment to the invoices it settles.
- **Payment portal** — a third-party system that issues/records payments and remittances (Ledger Run,
  Ramp, eClinicalGPS).
- **Autopay** — a payment a portal issues for an activity **automatically, with no site invoice**. Some
  studies pay per visit this way.
- **Holdback / withholding** — a fixed % the sponsor keeps back from each payment per the CTA (released
  at study close). With a 10% holdback, a payment of 90% of face is **paid in full per terms** — not underpaid.
- **Overhead (OH)** — a markup the site adds on top of raw procedure cost (e.g. +25%). Means an invoiced
  total won't equal the CTA's base amount for the visit.
- **Net 30 / Net 45** — payment terms: the invoice is due within that many days of receipt.
- **AR (Accounts Receivable) / "outstanding"** — money the site has billed but not yet collected.

**Systems & vendors** — just software products; you only need to read their exports, not know them:
- **CTMS (Clinical Trial Management System)** — where the site logs visits/activities. Vendors here:
  RealTime, CRIO, Clinical Conductor, eClinPro. Each exports a different column layout.
- **Plaid** — a service that aggregates a bank account's transactions into one feed/export.
- (Ledger Run, Ramp, eClinicalGPS are the payment portals defined above.)

**Reconciliation terms**
- **Reconciliation** — matching all these documents against each other so that, for every dollar of work,
  you can say: was it invoiced? paid? at the right amount? what's still owed or was missed?
- **Match-chain** — a resolved mapping between two entity types (e.g. invoice → payment). The six you
  must produce are listed under "Your task."
- **Exception** — something that doesn't reconcile cleanly and a human should review (billed over a cap,
  paid the wrong amount, etc.).
- **Days to payment** — days between an invoice's date and when it was paid; averaged for the dashboard.

## Your task

**You are the one reconciling this site's billing, and your job is to deliver that reconciliation to the
client (the site) through a service you build.** Doing the reconciliation is the work: ingest the
document pile, organize and model it, and resolve how the money actually flowed. Then build a service
that **exposes your reconciliation as a queryable interface**, so the client can see where they stand —
dashboards, invoices for unbilled work, and payments that never arrived.

To put it plainly: the reconciliation is *your* deliverable; the service is how you hand it to the
client. Both matter — a correct reconciliation served through a sloppy interface, or a clean interface
over a wrong reconciliation, both fall short.

Concretely, your reconciliation must resolve these **six match-chains**, and your service must expose
them:

1. **payment → remittance** — which remittance explains each payment
2. **invoice → payment** — which payment(s) settled each invoice, and for how much
3. **invoice → activities** — which activities each invoice billed
4. **remittance → activities** — which activities each remittance line paid for
5. **activity → CTA** — which CTA visit/line each activity bills against (or none)
6. **everything → study · site · investigator** — every entity scoped to the right trial tenant

…and from those, three **derived products** your service delivers to the client (these are the
acceptance tests for your reconciliation):

- **A dashboard** per study·site·investigator: total billed, total collected, outstanding AR, holdback
  withheld, an estimate of unbilled revenue, exception count, average days to payment.
- **Invoices for unbilled activities** — work that has evidence it happened but was never invoiced.
- **Payments / autopays that never paid** — invoices sent or autopays expected that never landed in the
  bank.

## What we are and aren't testing

- **We ARE testing:** your **data model / schema design** (how you represent entities and the chains so
  they're queryable and extensible) and your **reconciliation correctness** (do you get the right
  answers on the hard cases below).
- **We are NOT testing document parsing.** Extract the PDFs/CSVs however you like — dropping them into
  any LLM is completely fine and expected. Some invoices are scanned images (no text layer), so a
  vision-capable model is the easy path; don't spend your time on OCR or PDF-layout heroics. Spend it
  on the model and the matching logic.

## Inputs — one unsorted pile (`documents/`)

Everything is in a **single flat folder, `documents/`** — every CTA, CTMS export, invoice, remittance,
payment-portal export, bank feed, and comm for **all three studies, mixed together and unsorted**, the
way it lands in a real billing inbox. We deliberately do **not** group it by study or by type, and you
must not trust filenames to tell you the study.

**Classifying each document is part of the task** — which study · site · investigator it belongs to,
and what kind of document it is — using its *contents* (study code on the CTA/invoice, sponsor/CRO/payor
names, subject ids, site numbers). The pile contains:

| Type | What it is | Notes |
|---|---|---|
| CTA | The contract: visit×procedure budget, site fees, billing rules (+ amendments) | one per study |
| CTMS export | Activity/visit logs (RealTime / CRIO / Clinical Conductor) | different columns per vendor |
| Invoice (PDF) | Invoices the site sent the sponsor | **some are scanned images** (no text layer) — use a vision model |
| Remittance (PDF) | Payment advices the sponsor/CRO sent back | |
| Portal export | Remittance / autopay registers (Ledger Run / eClinicalGPS / Ramp) | |
| Bank feed (CSV) | One Plaid export for the network's shared operating account, all studies intermixed | a single file for all three studies; no invoice numbers. Match by amount / date / payor, then scope each line to a study |
| Comms | Emails / Slack | some carry the only signal that resolves a status |
| ClinCard receipt (PDF) | Subject travel/time reimbursement receipts (Greenphire ClinCard) | a **subject** payment, not site billing; proof a visit happened — corroborates unbilled work. Watch for a typo'd subject id |

The three studies use **different vendors on purpose**. A solution that hard-codes to one study's
format — or trusts a filename to tell it the study — will fail.

## The studies

The pile covers three trials. Use these exact slugs for your `out/<study>/` folders:

| Study code | Protocol | `out/` slug |
|---|---|---|
| `MRD-204-017` | HORIZON | `study-01-horizon` |
| `VTX-330-201` | ASCEND | `study-02-ascend` |
| `CLX-115-300` | NORTHSTAR | `study-03-northstar` |

Knowing the three trials exist is the easy part — assigning each of the ~60 documents to the right one,
by content, is the work.

## Output — what your service must produce

Your service must be able to write a set of **canonical answer files** under `out/<study>/`:
`chains.json`, `dashboard.json`, `unbilled.json`, `unpaid.json`. The exact shapes are in
**`OUTPUT_CONTRACT.md`** with JSON Schemas in `conformance/schemas/`. **These files are what we grade**
— but they must be *produced by your service* (e.g. a `make reconcile` that calls your own API and dumps
them), not hand-written. On day 3 you'll demo the live service that produced them.

## The hard cases (these are where the points are)

We grade against a hidden, fully-reconciled ground truth. The same patterns appear across the studies;
some are designed so the naive answer is wrong:

1. **Holdbacks.** Some sponsors withhold a fixed % per the CTA. An invoice paid at 90% of face may be
   **paid in full per terms**, not underpaid. Don't flag it as a shortfall.
2. **One payment, many invoices (and vice-versa).** A single wire can cover several invoices; only the
   remittance splits it. Reconcile at the line level, not the payment level.
3. **Reused invoice numbers.** The same invoice "number" is reused for different work. The number is not
   a key.
4. **Procedure-level vs contracted amounts.** Invoiced totals may include an overhead markup, so they
   won't equal the CTA's face amount for the visit. Match to the right line anyway.
5. **Unbilled work.** Some subjects have evidence they were seen (CTMS logs, subject-payment receipts)
   but no invoice. Those are the unbilled-activities product.
6. **Autopays that never landed.** A portal can mark an activity "autopaid" while the bank never shows
   the deposit. Those are the unpaid-autopay product. (An autopay paid at the *wrong amount* is a
   different thing — an exception, not an unpaid item.)
7. **Unpaid invoices & status that only lives in comms.** An invoice may be sent but never paid (no
   remittance, no matching bank deposit). Whether it's disputed, "no partial pay", or written off may
   only be stated in an email or Slack thread. Read the comms.
8. **Wrong-tenant documents.** Documents arrive unsorted; some reference a typo'd site. Scope every
   entity to the correct study·site·investigator by its contents, not its filename.
9. **Mislabeled study code.** A document can be stamped with the *wrong* protocol/study code, and two
   studies can share the same site and investigator, so neither the printed code nor the site/PI is
   enough to scope it. Confirm the study from the chain that actually pays the document (its remittance,
   payment, and bank deposit) and from the activities it bills. Trust the corroborated evidence over a
   single printed field.

## Scaffolding we give you

You should not lose a day to plumbing. We provide:

- **`docker-compose.yml`** with a Postgres you may use as your store (or use SQLite, files, anything —
  designing the store is part of the exercise, but you don't have to provision infra).
- **`app-skeleton/`** — minimal, runnable hello-world services in **Python, Node, and Go**, each with a
  Dockerfile that already boots and serves a health check. Pick one as a starting point, or bring your
  own stack. There are no parsing dependencies baked in — that's deliberate (see "what we're testing").
- **`conformance/run_conformance.py`** — validates your `out/` files against the schemas and scores them
  against a small **public sample** so you can iterate. Your real grade is against the full hidden set,
  so a good self-eval score isn't a guarantee.

## Scoring

| Weight | Component |
|---|---|
| 40% | Correctness of the derived answers + the six chains, diffed against the hidden ground truth |
| 30% | Code quality, data model, and design — we read the repo and run your service |
| 30% | Day-3 walkthrough — your reasoning on the hard cases above |

## Allowed tools

Anything — any language, any libraries, any LLM for extraction or coding help. We're scoring the result
and the design, not your keystrokes.

## Submission

When you're done (within your 3-day window), open your **submit link** and paste a link to a single
git repo (or zip) containing:

1. Your service code, runnable on a clean machine with one documented command (`docker compose up`,
   `make run`, etc.).
2. A `make reconcile` (or equivalent) that runs your service over `data/` and writes `out/<study>/`.
3. The `out/` you produced.
4. A `README.md` covering: how to run, your data model (a diagram or a few paragraphs), the hard cases
   you handled and how, what you'd build next, and roughly how long you spent.

We'll run it ourselves to confirm it reproduces, diff your `out/` against the hidden ground truth, read
your model, and do a 60-minute walkthrough.

Good luck.
