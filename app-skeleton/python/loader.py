"""
loader.py — Data I/O for the reconciliation engine.
Loads extracted JSON cache files and CSV data sources from the documents directory.
"""
import csv
import glob
import json
from pathlib import Path

def load_cache(cache_dir: Path) -> list[dict]:
    items = []
    if cache_dir.exists():
        for f in sorted(glob.glob(str(cache_dir / "*.json"))):
            with open(f, "r") as fp:
                items.append(json.load(fp))
    return items


def load_csv(data_dir: Path, name: str) -> list[dict]:
    rows = []
    path = data_dir / name
    if path.exists():
        with open(path, "r") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    return rows


DATA_SOURCES = {
    "bank_feed": "plaid_transactions.csv",
    "ctms_rt": "realtime_visit_log.csv",
    "ctms_crio": "crio_activities.csv",
    "ctms_cc": "clinical_conductor_visits.csv",
    "reg_lr": "ledger_run_payment_register.csv",
    "reg_ramp": "ramp_bill_pay_register.csv",
    "reg_eclin": "eclinicalgps_autopay_register.csv",
}

def load_all_data(data_dir: Path, cache_dir: Path) -> dict:
    """
    Load all data sources into a single structured dict based on DATA_SOURCES config.
    """
    data = {"items": load_cache(cache_dir)}
    for key, filename in DATA_SOURCES.items():
        data[key] = load_csv(data_dir, filename)
    return data
