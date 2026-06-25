#!/usr/bin/env python3
"""
Orchestrator for the clinical trial reconciliation engine
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from loader import load_all_data
from domain.metadata import build_study_meta
from services.reconciliation import (
    match_deposits,
    match_invoices,
    match_autopays,
)
from domain.models import Invoice, Deposit, Remittance, Comm
from utils.logger import get_logger

logger = get_logger(__name__)
from utils.financial import to_cents, amounts_match
from services.routing import find_study_key
from services.ctms import (
    normalize_realtime,
    normalize_crio,
    normalize_clinical_conductor,
    detect_unbilled,
)
from services.chains import (
    compute_avg_days_to_payment,
    get_all_activities,
    build_invoice_to_activities,
    build_remittance_to_activities,
    build_activity_to_cta,
    build_entity_scope,
)
from services.reporting import generate_reports

DATA = Path(os.environ.get("DATA_DIR", "documents"))
OUT = Path(os.environ.get("OUT_DIR", "out"))
CACHE = Path("app-skeleton/python/cache")


# ──────────────────────────────────────────────────────────
#  Reconciliation orchestrator
# ──────────────────────────────────────────────────────────

def reconcile():
    # Load all data 
    data = load_all_data(DATA, CACHE)
    items = data["items"]
    # Build study metadata from CTAs 
    study_meta, study_key_order = build_study_meta(items)
    # Categorise parsed documents
    invoices_raw = [i for i in items if i.get("type") == "Invoice"]
    comms_raw = [i for i in items if i.get("type") == "Comm"]
    remittances_raw = [i for i in items if i.get("type") == "Remittance"]
    deposits_raw = [row for row in data["bank_feed"] if float(row.get("amount", 0)) > 0]
    
    invoices = [Invoice.from_dict(i) for i in invoices_raw]
    remittances = [Remittance.from_dict(r) for r in remittances_raw]
    deposits = [Deposit.from_dict(d) for d in deposits_raw]
    comms = [Comm.from_dict(c) for c in comms_raw]
    
    logger.info(f"Loaded {len(invoices)} invoices, {len(remittances)} remittances, {len(deposits)} deposits, {len(comms)} comms.")
    
    # Phase 0: Map Invoices to Studies
    for inv in invoices:
        inv.study_key = find_study_key(inv, study_meta)
    # 1: Map deposits to studies + remittances (should be correct)
    deposit_map = match_deposits(deposits, study_meta, data["reg_lr"], data["reg_ramp"], remittances, invoices)
    # Phase 2: Match invoices to payments (done)
    inv_results = match_invoices(invoices, deposit_map, study_meta, study_key_order, comms)
    # Phase 3: Match autopays to deposits
    ap_results = match_autopays(data["reg_eclin"], deposit_map, study_meta)
    # Phase 4: Detect unbilled visits
    visit_logs = []
    visit_logs.extend(normalize_realtime("study-01-horizon", data["ctms_rt"]))
    visit_logs.extend(normalize_crio("study-02-ascend", data["ctms_crio"]))
    visit_logs.extend(normalize_clinical_conductor("study-03-northstar", data["ctms_cc"]))
    unbilled_results = detect_unbilled(visit_logs, invoices, study_meta)

    # Phase 5: Build chains and assemble output 
    results = generate_reports(study_meta, invoices, remittances, deposit_map, inv_results, ap_results, unbilled_results, comms, visit_logs)

    # Write output 
    for s_key in results:
        d = OUT / s_key
        d.mkdir(parents=True, exist_ok=True)
        (d / "chains.json").write_text(json.dumps(results[s_key]["chains"], indent=2))
        (d / "dashboard.json").write_text(json.dumps(results[s_key]["dashboard"], indent=2))
        (d / "unbilled.json").write_text(json.dumps(results[s_key]["unbilled"], indent=2))
        (d / "unpaid.json").write_text(json.dumps(results[s_key]["unpaid"], indent=2))

    logger.info("Reconciliation complete!")
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
            
        if self.path == "/api/studies":
            if not OUT.exists():
                return self._send(200, {"studies": []})
            studies = [d.name for d in OUT.iterdir() if d.is_dir()]
            return self._send(200, {"studies": studies}) 
        if self.path.startswith("/api/study/"):
            parts = self.path.strip("/").split("/")
            if len(parts) >= 3:
                study_id = parts[2]
                resource = parts[3] if len(parts) > 3 else None
                study_dir = OUT / study_id
                if not study_dir.exists():
                    return self._send(404, {"error": f"Study {study_id} not found"})
                if not resource:
                    return self._send(404, {"error": f"Internal Server Error"})
                    
                target_file = study_dir / f"{resource}.json"
                if target_file.exists():
                    data = json.loads(target_file.read_text())
                    return self._send(200, data)
                else:
                    return self._send(404, {"error": f"Internal Server Error"})
                    
        self._send(404, {"error": "Not Found"})


if __name__ == "__main__":
    if "--reconcile" in sys.argv:
        reconcile()
        print("Reconciliation complete")
    else:
        print("serving on :8080")
        HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
