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


def load_all_data(data_dir: Path, cache_dir: Path) -> dict:
    """
    Load all data sources into a single structured dict.

    Returns a dict with keys:
        items           – list of all parsed document JSON objects
        bank_feed       – plaid_transactions.csv rows
        ctms_rt         – realtime_visit_log.csv rows
        ctms_crio       – crio_activities.csv rows
        ctms_cc         – clinical_conductor_visits.csv rows
        reg_lr          – ledger_run_payment_register.csv rows
        reg_ramp        – ramp_bill_pay_register.csv rows
        reg_eclin       – eclinicalgps_autopay_register.csv rows
    """
    return {
        "items": load_cache(cache_dir),
        "bank_feed": load_csv(data_dir, "plaid_transactions.csv"),
        "ctms_rt": load_csv(data_dir, "realtime_visit_log.csv"),
        "ctms_crio": load_csv(data_dir, "crio_activities.csv"),
        "ctms_cc": load_csv(data_dir, "clinical_conductor_visits.csv"),
        "reg_lr": load_csv(data_dir, "ledger_run_payment_register.csv"),
        "reg_ramp": load_csv(data_dir, "ramp_bill_pay_register.csv"),
        "reg_eclin": load_csv(data_dir, "eclinicalgps_autopay_register.csv"),
    }
