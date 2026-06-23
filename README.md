# Reconciliation Service — SWE Take-Home

Start with **`ASSIGNMENT.md`** — the full problem statement, output contract, and submission rules.

## What's in this folder

```
.
├── ASSIGNMENT.md            ← read this first
├── OUTPUT_CONTRACT.md       ← the exact answer files your service must produce (this is what we grade)
├── README.md                ← (this file)
├── docker-compose.yml       ← optional: a Postgres you may use as your store (or bring your own)
├── app-skeleton/            ← runnable hello-world services in Python / Node / Go — pick one or ignore
│   ├── python/  node/  go/
│   └── README.md
├── conformance/             ← self-check: validates your out/ files and scores them vs a public sample
│   ├── run_conformance.py
│   ├── schemas/             ← JSON Schemas for each required answer file
│   └── public-sample/       ← a small labeled subset so you can score yourself
└── documents/               ← ONE flat folder: every document for all 3 studies, unsorted
```

`documents/` is deliberately **not** organized — ~60 files (CTAs, CTMS exports, invoices, remittances,
portal exports, bank feeds, emails/Slack) for all three trials, mixed together like a real billing
inbox. Sorting them out (which study·site·investigator, what type) is part of the task.

## Quick start

1. Read `ASSIGNMENT.md`, then `OUTPUT_CONTRACT.md`.
2. Look at the pile:
   ```bash
   ls documents/ | head -40
   ```
3. Parse the PDFs/CSVs however you like (any LLM is fine — parsing is not what we're testing; some
   invoices are scanned images, so use a vision-capable model). Then build your service: ingest →
   classify each document by study → model → reconcile → serve.
4. Produce the canonical answer files under `out/<study>/` (schemas in `conformance/schemas/`).
5. Self-score against the public sample:
   ```bash
   python3 conformance/run_conformance.py --out ./out
   ```
6. Submit per `ASSIGNMENT.md`.

## A note on the inputs

The data is synthetic but modeled on real clinical-trial billing: real-world holdbacks,
lump-sum payments, invoice numbers that collide across studies, free-text visit naming, scanned-image invoices, and
documents you must scope to the right trial by their contents. Subject identifiers are synthetic; there
is no PHI. The three studies span variety — a large, messy study; a clean study with an autopay portal;
and a small third study on different vendors that will break anything you hard-coded to the first two.
