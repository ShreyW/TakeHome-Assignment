import os
import glob
import json
import csv
from datetime import datetime
from collections import defaultdict
import math

CACHE_DIR = "cache"
DATA_DIR = "../../documents"
STUDIES = ["study-01-horizon", "study-02-ascend", "study-03-northstar"]

# Known mappings to deal with mislabels
STUDY_IDS = {
    "MRD-204-017": "study-01-horizon",
    "VTX-330-201": "study-02-ascend",
    "CLX-115-300": "study-03-northstar"
}

def load_data():
    data = {
        "ctas": [],
        "invoices": [],
        "remittances": [],
        "clincards": [],
        "comms": [],
        "bank_feed": [],
        "ctms": [],
        "registers": []
    }

    # Load Extracted JSONs
    for fpath in glob.glob(os.path.join(CACHE_DIR, "*.json")):
        with open(fpath, "r") as f:
            obj = json.load(f)
            t = obj.get("type", "")
            if t == "CTA": data["ctas"].append(obj)
            elif t == "Invoice": data["invoices"].append(obj)
            elif t == "Remittance": data["remittances"].append(obj)
            elif t == "ClinCard": data["clincards"].append(obj)
            elif t == "Comm": data["comms"].append(obj)
            else:
                print(f"Unknown type {t} in {fpath}")

    # Load CSVs
    def load_csv(name):
        res = []
        path = os.path.join(DATA_DIR, name)
        if os.path.exists(path):
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    res.append(row)
        return res

    data["bank_feed"] = load_csv("plaid_transactions.csv")
    data["ctms"].extend([{"source": "RealTime", **r} for r in load_csv("realtime_visit_log.csv")])
    data["ctms"].extend([{"source": "CRIO", **r} for r in load_csv("crio_activities.csv")])
    data["ctms"].extend([{"source": "ClinicalConductor", **r} for r in load_csv("clinical_conductor_visits.csv")])
    
    data["registers"].extend([{"source": "LedgerRun", **r} for r in load_csv("ledger_run_payment_register.csv")])
    data["registers"].extend([{"source": "Ramp", **r} for r in load_csv("ramp_bill_pay_register.csv")])
    data["registers"].extend([{"source": "eClinicalGPS", **r} for r in load_csv("eclinicalgps_autopay_register.csv")])

    return data

def reconcile():
    data = load_data()
    print(f"Loaded {len(data['invoices'])} invoices, {len(data['remittances'])} remittances, {len(data['ctms'])} activities")
    
    # Initialize outputs per study
    outputs = {s: {
        "chains": {
            "study_id": s.split("-")[1] if len(s.split("-")) > 1 else "",
            "site_id": "",
            "investigator": "",
            "payment_to_remittance": [],
            "invoice_to_payment": [],
            "invoice_to_activities": [],
            "remittance_to_activities": [],
            "activity_to_cta": [],
            "entity_scope": []
        },
        "dashboard": {
            "study_id": s,
            "site_id": "",
            "investigator": "",
            "total_billed": 0,
            "total_collected": 0,
            "outstanding_ar": 0,
            "holdback_withheld": 0,
            "unbilled_estimate": 0,
            "exceptions_count": 0,
            "avg_days_to_payment": None
        },
        "unbilled": [],
        "unpaid": []
    } for s in STUDIES}

    # TO DO: Reconcile logic
    
    return outputs

if __name__ == "__main__":
    reconcile()
