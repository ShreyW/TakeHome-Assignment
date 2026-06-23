# Output Contract

Your service designs its own endpoints — but for grading it must emit four **canonical answer files per
study**, produced by your service (not hand-authored):

```
out/
  study-01-horizon/   chains.json  dashboard.json  unbilled.json  unpaid.json
  study-02-ascend/    chains.json  dashboard.json  unbilled.json  unpaid.json
  study-03-northstar/ chains.json  dashboard.json  unbilled.json  unpaid.json
```

Conventions, everywhere:
- Money is a JSON **number**, dollars, 2 decimals (e.g. `1937.82`). No currency symbols, no strings.
- Dates are ISO `YYYY-MM-DD`.
- IDs are **your** stable surrogate keys. They must be consistent *across the four files* (an
  `activity_id` in `chains.json` must be the same id used in `unbilled.json`). We grade by the
  relationships and amounts you assert, and by matching your entities to ours on natural keys
  (subject + visit + date + amount), so you do **not** need to guess our id strings.
- For anything genuinely unmatched, use `null` (not `""`), and say why in the `notes` field where one
  exists. Honest `null` + reason beats a wrong guess.

JSON Schemas for all four files are in `conformance/schemas/`. `run_conformance.py` validates against
them and scores the public sample.

---

## `chains.json` — the six match-chains

```jsonc
{
  "study_id": "MRD-204-017",
  "site_id": "ARP-12",
  "investigator": "Elena Park",

  // 1. payment -> remittance
  "payment_to_remittance": [
    { "payment_id": "P-001", "remittance_ids": ["R-001"], "notes": null }
  ],

  // 2. invoice -> payment  (amount_settled = what actually cleared toward this invoice)
  "invoice_to_payment": [
    { "invoice_id": "INV-002", "payment_ids": ["P-001"],
      "invoice_amount": 2153.13, "amount_settled": 1937.82,
      "status": "paid|partial|unpaid",   // "paid" includes paid-in-full-per-terms after holdback
      "notes": "10% CTA holdback; 1937.82 = 2153.13 x 0.90" }
  ],

  // 3. invoice -> activities
  "invoice_to_activities": [
    { "invoice_id": "INV-002", "activity_ids": ["A-014"] }
  ],

  // 4. remittance -> activities  (line-level allocation)
  "remittance_to_activities": [
    { "remittance_id": "R-007",
      "lines": [ { "activity_id": "A-302", "amount_allocated": 3200.00 },
                 { "activity_id": "A-303", "amount_allocated": 15440.00 } ] }
  ],

  // 5. activity -> CTA  (which contracted line it bills; null if none, e.g. admin/log-only)
  "activity_to_cta": [
    { "activity_id": "A-014", "cta_visit_label": "Screening",
      "cta_amount": 2153.13, "match_confidence": "HIGH|MEDIUM|LOW", "notes": null }
  ],

  // 6. everything -> study / site / investigator
  "entity_scope": [
    { "entity_type": "invoice|payment|remittance|activity",
      "entity_id": "INV-002", "study_id": "MRD-204-017",
      "site_id": "ARP-12", "investigator": "Elena Park" }
  ]
}
```

Notes:
- `status` on `invoice_to_payment`: use `paid` when the invoice is satisfied per the CTA terms
  (including after a contractual holdback). `partial` only for a genuine shortfall. `unpaid` when
  nothing cleared — no remittance and no matching bank deposit (it shows up in `unpaid.json`).

## `dashboard.json` — one object per study

```jsonc
{
  "study_id": "MRD-204-017",
  "site_id": "ARP-12",
  "investigator": "Elena Park",
  "total_billed": 146305.27,          // sum of invoice face amounts (your reconciled set)
  "total_collected": 130102.76,       // cash actually received (net of holdback/fees)
  "outstanding_ar": 12000.00,         // billed but not yet collected
  "holdback_withheld": 9274.47,       // total withheld under CTA holdback terms
  "unbilled_estimate": 38143.80,      // your estimate of work done but never invoiced
  "exceptions_count": 3,              // cap breaches, wrong-amount autopays, disputes, etc.
  "avg_days_to_payment": 118.3        // mean(payment_date - invoice_date) over settled invoices
}
```

We grade dashboard numbers with tolerance: exact on counts, within a small band on dollar aggregates,
so your reasonable modeling choices aren't punished.

## `unbilled.json` — work that happened but was never invoiced

```jsonc
[
  { "subject_id": "S-12-037",
    "evidence": "RealTime CTMS visit log: Screening + Ultrasound completed; no site invoice found",
    "proposed_visit_label": "Screening+TVU",
    "estimated_amount": 3814.38,
    "cta_basis": "Screening+TVU procedure-level + 25% overhead",
    "confidence": "HIGH|MEDIUM|LOW" }
]
```

## `unpaid.json` — issued/expected but never landed in the bank

```jsonc
[
  { "ref_type": "invoice|autopay",
    "ref_id": "INV-105",
    "amount_expected": 12000.00,
    "age_days": 129,
    "reason": "sent_not_paid|autopay_no_deposit",
    "evidence": "Invoice sent 2026-02-06; no remittance and no matching bank deposit; comms confirm unpaid",
    "confidence": "HIGH|MEDIUM|LOW" }
]
```

Keep these two lists disciplined: an autopay paid at the *wrong amount* belongs in your exceptions /
dashboard count, **not** in `unpaid.json`. A holdback is not an unpaid item. Precision matters here —
over-reporting is penalized like under-reporting.
