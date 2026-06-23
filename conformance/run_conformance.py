#!/usr/bin/env python3
"""Self-check your reconciliation output. Dependency-free (Python 3.8+ stdlib only).

  python3 conformance/run_conformance.py --out ./out

Does two things per study:
  1. STRUCTURE — validates out/<study>/{chains,dashboard,unbilled,unpaid}.json against the shapes in
     conformance/schemas/ (required fields + types; a light check, not a full JSON-Schema validator).
  2. PUBLIC SAMPLE — scores your answers against a small public subset of the hidden ground truth.

A good sample score is encouraging but NOT a guarantee — the real grade is the full hidden set.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE / "schemas"
SAMPLES = HERE / "public-sample"
STUDIES = ["study-01-horizon", "study-02-ascend", "study-03-northstar"]
FILES = ["chains", "dashboard", "unbilled", "unpaid"]


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except FileNotFoundError:
        return ("__missing__", p)
    except json.JSONDecodeError as e:
        return ("__badjson__", f"{p}: {e}")


# ---- minimal structural validation (top-level required fields + array-ness) ----
def structure_errors(name, data):
    errs = []
    if isinstance(data, tuple):
        return [f"{name}: {data[0].strip('_')} ({data[1]})"]
    if name in ("unbilled", "unpaid"):
        if not isinstance(data, list):
            return [f"{name}.json must be a JSON array"]
        req = {"unbilled": ["subject_id", "estimated_amount"],
               "unpaid": ["ref_type", "ref_id", "amount_expected", "reason"]}[name]
        for i, row in enumerate(data[:200]):
            miss = [k for k in req if k not in row]
            if miss:
                errs.append(f"{name}[{i}] missing {miss}")
    elif name == "dashboard":
        req = ["study_id", "total_billed", "total_collected", "outstanding_ar",
               "unbilled_estimate", "exceptions_count"]
        miss = [k for k in req if k not in data]
        if miss:
            errs.append(f"dashboard.json missing {miss}")
    elif name == "chains":
        req = ["study_id", "payment_to_remittance", "invoice_to_payment", "invoice_to_activities",
               "remittance_to_activities", "activity_to_cta", "entity_scope"]
        miss = [k for k in req if k not in data]
        if miss:
            errs.append(f"chains.json missing {miss}")
    return errs[:8]


# ---- public-sample checks ----
def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def run_check(c, out):
    chains, dash = out.get("chains") or {}, out.get("dashboard") or {}
    unbilled, unpaid = out.get("unbilled") or [], out.get("unpaid") or []
    k = c["kind"]
    if k == "invoice_status":
        for r in chains.get("invoice_to_payment", []):
            if abs((num(r.get("invoice_amount")) or -1) - c["match_amount"]) <= 0.5:
                ok = str(r.get("status", "")).lower() == c["expect_status"]
                ok &= abs((num(r.get("amount_settled")) or -1) - c["expect_settled"]) <= 0.5
                return ok
        return False
    if k == "unpaid_present":
        return any(str(r.get("ref_type")) == c["ref_type"] and
                   abs((num(r.get("amount_expected")) or -1) - c["amount"]) <= 0.5 for r in unpaid)
    if k == "unbilled_subject":
        return any(str(r.get("subject_id")) == c["subject_id"] for r in unbilled)
    if k == "exception_count_min":
        return (num(dash.get("exceptions_count")) or 0) >= c["value"]
    if k == "dashboard_field":
        return abs((num(dash.get(c["field"])) or -1e9) - c["value"]) <= c.get("tol", 0.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./out", help="directory containing study-XX/*.json")
    args = ap.parse_args()
    out_root = Path(args.out)

    total_pass = total_checks = struct_fail = 0
    for slug in STUDIES:
        print(f"\n{'='*64}\n{slug}")
        out = {f: load(out_root / slug / f"{f}.json") for f in FILES}
        # structure
        serrs = []
        for f in FILES:
            serrs += structure_errors(f, out[f])
        if serrs:
            struct_fail += 1
            print("  STRUCTURE: ✗")
            for e in serrs:
                print(f"     - {e}")
        else:
            print("  STRUCTURE: ✓ all four files present and well-formed")
        # normalize tuples to empty for sample scoring
        clean = {f: (v if not isinstance(v, tuple) else ({} if f != "unbilled" and f != "unpaid" else []))
                 for f, v in out.items()}
        sample = load(SAMPLES / f"{slug}.json")
        if isinstance(sample, tuple):
            continue
        print("  PUBLIC SAMPLE:")
        for c in sample["checks"]:
            ok = run_check(c, clean)
            total_checks += 1
            total_pass += 1 if ok else 0
            print(f"     [{'PASS' if ok else 'FAIL'}] {c['kind']}: {c['hint']}")

    print(f"\n{'='*64}")
    print(f"PUBLIC SAMPLE: {total_pass}/{total_checks} checks passed"
          f"{'' if not struct_fail else f'   ({struct_fail} study/studies had structure errors)'}")
    print("Reminder: the public sample is a small subset. Your real grade is the full hidden set.")


if __name__ == "__main__":
    main()
