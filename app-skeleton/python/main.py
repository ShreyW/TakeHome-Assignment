#!/usr/bin/env python3
"""
main.py — Orchestrator for the clinical trial reconciliation engine.

This is the entry point that wires together the modular components:
  - loader.py      → data I/O
  - study_meta.py  → CTA metadata construction
  - matcher.py     → invoice/deposit/autopay matching
  - chains.py      → chain building, entity scope, metrics
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from loader import load_all_data
from study_meta import build_study_meta
from matcher import (
    find_study_key,
    match_deposits,
    match_invoices,
    match_autopays,
    detect_unbilled,
)
from chains import (
    compute_avg_days_to_payment,
    get_all_activities,
    build_invoice_to_activities,
    build_remittance_to_activities,
    build_activity_to_cta,
    build_entity_scope,
)

DATA = Path(os.environ.get("DATA_DIR", "documents"))
OUT = Path(os.environ.get("OUT_DIR", "out"))
CACHE = Path("app-skeleton/python/cache")


# ──────────────────────────────────────────────────────────
#  Core reconciliation orchestrator
# ──────────────────────────────────────────────────────────

def reconcile():
    print("Running fully dynamic reconciliation logic...")
    # ── Load all data 
    data = load_all_data(DATA, CACHE)
    items = data["items"]
    # ── Build study metadata from CTAs 
    study_meta, study_key_order = build_study_meta(items)
    # ── Categorise parsed documents ──────────────────────
    invoices = [i for i in items if i.get("type") == "Invoice"]
    comms = [i for i in items if i.get("type") == "Comm"]
    remittances = [i for i in items if i.get("type") == "Remittance"]
    deposits = [row for row in data["bank_feed"] if float(row.get("amount", 0)) > 0]
    
    # ── Phase 1: Map deposits to studies + remittances (should be correct)
    deposit_map = match_deposits(deposits, study_meta, data["reg_lr"], data["reg_ramp"], remittances, invoices)
    # ── Phase 2: Match invoices to payments (reviewed)
    inv_results = match_invoices(invoices, deposit_map, study_meta, study_key_order, comms)
    # ── Phase 3: Match autopays to deposits
    ap_results = match_autopays(data["reg_eclin"], deposit_map, study_meta)
    # ── Phase 4: Detect unbilled visits ──────────────────
    unbilled_results = detect_unbilled(data["ctms_cc"], data["ctms_rt"], data["ctms_crio"], invoices, study_meta)

    # ── Phase 5: Build chains and assemble output ────────
    results = {}
    for s_key, meta in study_meta.items():
        # Get study-specific invoices for chain building
        study_invoices = [inv for inv in invoices if find_study_key(inv, study_meta) == s_key]

        # Get study-specific remittances
        # We route by checking if the remittance explicitly pays an invoice belonging to this study.
        study_inv_ids = {inv.get("invoice_id") for inv in study_invoices}
        study_remittances = []
        for rem in remittances:
            valid_lines_for_study = 0
            invalid_lines_for_study = 0
            
            for line in rem.get("lines", []):
                r_inv_id = line.get("invoice_id")
                # Does this invoice exist in this study?
                inv_match = next((i for i in study_invoices if i.get("invoice_id") == r_inv_id), None)
                
                if inv_match:
                    inv_amt = float(inv_match.get("total_amount", 0))
                    line_gross = float(line.get("gross_amount", line.get("amount_paid", 0)))
                    line_paid = float(line.get("amount_paid", 0))
                    expected_settled = inv_amt * (1 - meta.get("holdback", 0))
                    
                    if abs(inv_amt - line_gross) < 0.01 or abs(expected_settled - line_paid) < 0.01:
                        valid_lines_for_study += 1
                    else:
                        invalid_lines_for_study += 1
                else:
                    invalid_lines_for_study += 1
            if valid_lines_for_study > 0 and invalid_lines_for_study == 0:
                study_remittances.append(rem)

        # print(f"study_key={s_key} | len(study_inv_ids)={len(study_inv_ids)} | study_inv_ids={study_inv_ids}")
        # print(f"study_key={s_key} | len(study_remittances)={len(study_remittances)} | study_remittances={[rem['remittance_id'] for rem in study_remittances]}")

        # Build payment_to_remittance from deposit map
        payment_to_remittance = []
        for txn_id, dep_info in deposit_map.items():
            r_id = dep_info.get("remittance_id")
            if dep_info["study_key"] == s_key:
                payment_to_remittance.append({
                    "payment_id": txn_id,
                    "remittance_ids": [r_id] if r_id else [],
                    "notes": None,
                })

        # Build the detailed chain arrays
        activity_index = get_all_activities(
            data["ctms_rt"], data["ctms_cc"], data["ctms_crio"],
            s_key, study_meta
        )
        inv_to_act = build_invoice_to_activities(study_invoices, activity_index)
        rem_to_act = build_remittance_to_activities(study_remittances, inv_to_act, s_key, study_meta)
        act_to_cta = build_activity_to_cta(activity_index, inv_to_act, study_invoices, s_key, study_meta)
        invoice_to_payment = inv_results.get(s_key, {}).get("invoice_to_payment", [])
        # print(f"study_key={s_key} | len(invoice_to_payment)={len(invoice_to_payment)} | invoice_to_payment={invoice_to_payment}")
        entity_scope = build_entity_scope(s_key, study_meta, invoice_to_payment, payment_to_remittance, activity_index)
        day_pairs = inv_results.get(s_key, {}).get("payment_day_pairs", [])
        avg_days = compute_avg_days_to_payment(day_pairs)

        # Compute total_collected from deposit map
        total_collected = sum(
            info["amount"] for info in deposit_map.values()
            if info["study_key"] == s_key
        )

        # Merge dashboard values
        inv_r = inv_results.get(s_key, {})
        ap_r = ap_results.get(s_key, {})
        ub_r = unbilled_results.get(s_key, {})

        results[s_key] = {
            "chains": {
                "study_id": meta["study_id"],
                "site_id": meta["site_id"],
                "investigator": meta["investigator"],
                "payment_to_remittance": payment_to_remittance,
                "invoice_to_payment": invoice_to_payment,
                "invoice_to_activities": inv_to_act,
                "remittance_to_activities": rem_to_act,
                "activity_to_cta": act_to_cta,
                "entity_scope": entity_scope,
            },
            "dashboard": {
                "study_id": meta["study_id"],
                "site_id": meta["site_id"],
                "investigator": meta["investigator"],
                "total_billed": inv_r.get("billed_total", 0) + ap_r.get("billed_total", 0),
                "total_collected": total_collected,
                "outstanding_ar": inv_r.get("outstanding_ar", 0),
                "holdback_withheld": inv_r.get("holdback_withheld", 0),
                "unbilled_estimate": ub_r.get("unbilled_estimate", 0),
                "exceptions_count": ap_r.get("exceptions_count", 0),
                "avg_days_to_payment": avg_days,
            },
            "unbilled": ub_r.get("unbilled", []),
            "unpaid": inv_r.get("unpaid", []) + ap_r.get("unpaid", []),
        }

    # ── Write output ─────────────────────────────────────
    for s_key in results:
        d = OUT / s_key
        d.mkdir(parents=True, exist_ok=True)
        (d / "chains.json").write_text(json.dumps(results[s_key]["chains"], indent=2))
        (d / "dashboard.json").write_text(json.dumps(results[s_key]["dashboard"], indent=2))
        (d / "unbilled.json").write_text(json.dumps(results[s_key]["unbilled"], indent=2))
        (d / "unpaid.json").write_text(json.dumps(results[s_key]["unpaid"], indent=2))

    return {"status": "done", "studies": list(results.keys()), "out": str(OUT)}


# ──────────────────────────────────────────────────────────
#  HTTP Server
# ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok")
        if self.path.startswith("/reconcile"):
            return self._send(200, reconcile())
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    if "--reconcile" in sys.argv:
        reconcile()
        print("Reconciliation complete")
    else:
        print("serving on :8080")
        HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
