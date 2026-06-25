from datetime import datetime

def compute_avg_days_to_payment(day_pairs: list[tuple[str, str]]) -> float:
    """
    Compute mean(payment_date - invoice_date) over settled invoices.

    Args:
        day_pairs: list of (invoice_date, payment_date) strings in YYYY-MM-DD format.

    Returns:
        Average days as a float, or 0 if no pairs.
    """
    if not day_pairs:
        return 0

    total_days = 0
    count = 0
    for inv_date_str, pay_date_str in day_pairs:
        try:
            inv_dt = datetime.strptime(inv_date_str, "%Y-%m-%d")
            pay_dt = datetime.strptime(pay_date_str, "%Y-%m-%d")
            total_days += (pay_dt - inv_dt).days
            count += 1
        except (ValueError, TypeError):
            continue

    return round(total_days / count, 1) if count > 0 else 0


def get_all_activities(ctms_rt: list[dict], ctms_cc: list[dict], ctms_crio: list[dict], study_key: str, study_meta: dict) -> dict:
    """
    Build a combined activity index for a given study:
    """
    meta = study_meta[study_key]
    activity_index = {}
    
    ctms_mapping = {
        "study-01-horizon": {"name": "RealTime CTMS", "log": ctms_rt},
        "study-02-ascend": {"name": "CRIO", "log": ctms_crio},
        "study-03-northstar": {"name": "Clinical Conductor", "log": ctms_cc},
    }
    
    mapping = ctms_mapping.get(study_key)
    if not mapping:
        return activity_index
        
    ctms_name = mapping["name"]
    ctms_log = mapping["log"]

    if ctms_name == "RealTime CTMS":
        for i, rt in enumerate(ctms_log):
            subj = rt.get("SubjectID", "")
            a_id = f"RT-{subj}-{i}"
            visit = rt.get("VisitName", "").lower()
            date = rt.get("VisitDate", "")
            activity_index.setdefault(subj, []).append((a_id, visit, date))

    elif ctms_name == "Clinical Conductor":
        for i, cc in enumerate(ctms_log):
            subj = cc.get("Subject", "")
            a_id = f"CC-{subj}-{i}"
            visit = cc.get("ProtocolVisit", "").lower()
            date = cc.get("VisitDate", "")
            activity_index.setdefault(subj, []).append((a_id, visit, date))

    elif ctms_name == "CRIO":
        for crio in ctms_log:
            subj = crio.get("patient_id", "")
            a_id = crio.get("activity_ref", f"CRIO-{subj}")
            visit = crio.get("visit_name", "").lower()
            date = crio.get("service_date", "")
            activity_index.setdefault(subj, []).append((a_id, visit, date))

    return activity_index


def build_invoice_to_activities(invoices: list[dict], activity_index: dict) -> list[dict]:
    """
    Link invoices to CTMS activity records by matching subject + visit + date.
    Returns a list of {invoice_id, activity_ids} entries.
    """
    result = []

    # Now match invoices to activities
    for inv in invoices:
        inv_subj = inv.get("subject_id", "")
        if not inv_subj or inv_subj not in activity_index:
            continue
        inv_id = inv.get("invoice_id", "")
        inv_date = inv.get("service_date", "")

        matched_ids = []
        for a_id, visit, a_date in activity_index[inv_subj]:
            # Match by date proximity or visit name overlap
            date_match = (inv_date == a_date) if inv_date and a_date else False
            visit_match = False
            for item in inv.get("line_items", []):
                desc = item.get("description", "").lower()
                if visit and visit in desc:
                    visit_match = True
                    break
            if date_match or visit_match:
                matched_ids.append(a_id)

        if matched_ids:
            result.append({
                "invoice_id": inv_id,
                "activity_ids": matched_ids,
            })
    # import json
    # print("\ninvoice_to_activities\n", json.dumps(result, indent=2))
    return result


def build_remittance_to_activities(remittances: list[dict], invoice_to_activities: list[dict], study_key: str,study_meta: dict) -> list[dict]:
    """
    Link remittance line items to activities via invoice mapping.
    Returns a list of {remittance_id, lines: [{activity_id, invoice_id, amount_allocated}]}.
    """
    # Build an invoice_id → activity_ids lookup
    inv_to_acts = {}
    for entry in invoice_to_activities:
        inv_to_acts[entry["invoice_id"]] = entry["activity_ids"]

    result = []
    for rem in remittances:
        rem_id = rem.get("remittance_id", "")
        lines_out = []
        for line in rem.get("lines", []):
            inv_id = line.get("invoice_id", "")
            amount = float(line.get("amount_paid", 0))
            activity_ids = inv_to_acts.get(inv_id, [])
            if activity_ids:
                for a_id in activity_ids:
                    lines_out.append({
                        "activity_id": a_id,
                        "invoice_id": inv_id,
                        "amount_allocated": amount / len(activity_ids),
                    })
            else:
                lines_out.append({
                    "activity_id": None,
                    "invoice_id": inv_id,
                    "amount_allocated": amount,
                })
        if lines_out:
            result.append({
                "remittance_id": rem_id,
                "lines": lines_out,
            })
    # import json
    # print("\nremittance_to_activities\n", json.dumps(result, indent=2))
    return result


def build_activity_to_cta(activity_index: dict, invoice_to_activities: list[dict],invoices: list[dict],study_key: str,study_meta: dict) -> list[dict]:
    """
    Map activities to CTA budget lines.
    Returns a list of {activity_id, cta_visit_label, cta_amount, match_confidence}.
    """
    meta = study_meta[study_key]
    budget = meta.get("budget", [])
    site_fees = meta.get("site_fees", [])
    overhead_pct = meta.get("overhead", 0)
    result = []

    # Build activity_id -> invoice lookup
    act_to_inv = {}
    inv_lookup = {inv.get("invoice_id", ""): inv for inv in invoices if inv.get("invoice_id")}
    for entry in invoice_to_activities:
        inv = inv_lookup.get(entry["invoice_id"])
        if inv:
            for a_id in entry["activity_ids"]:
                act_to_inv[a_id] = inv

    # Process ALL activities
    for subj, activities in activity_index.items():
        for a_id, visit, a_date in activities:
            best_label = None
            best_amount = None
            best_confidence = None
            inv = act_to_inv.get(a_id)

            if inv:
                # Try to match invoice line items to CTA budget
                for item in inv.get("line_items", []):
                    desc = item.get("description", "").lower()
                    if "overhead" in desc:
                        continue
                    for b in budget:
                        b_name = b.get("visit_name", "").lower()
                        base = float(b.get("amount", 0))
                        item_amt = float(item.get("amount", 0))
                        
                        # Match by vocabulary OR exact base amount match
                        if b_name in desc or desc in b_name or abs(base - item_amt) < 0.01:
                            billed = base * (1 + overhead_pct / 100.0)
                            best_label = b.get("visit_name")
                            best_amount = round(billed, 2)
                            
                            if b_name in desc or desc in b_name:
                                best_confidence = "HIGH"
                            else:
                                best_confidence = "MEDIUM" # matched by amount only
                            break
                    if best_label:
                        break

                # Try site fees if no budget match
                if not best_label:
                    for item in inv.get("line_items", []):
                        desc = item.get("description", "").lower()
                        for sf in site_fees:
                            sf_name = sf.get("name", "").lower()
                            if sf_name and sf_name in desc:
                                best_label = sf.get("name")
                                best_amount = float(sf.get("amount", 0))
                                best_confidence = "HIGH"
                                break
                        if best_label:
                            break
            else:
                # No invoice (autopay or unbilled)
                v_lower = visit.lower()
                note_str = None
                for b in budget:
                    b_name = b.get("visit_name", "").lower()
                    if b_name in v_lower or v_lower in b_name:
                        base = float(b.get("amount", 0))
                        billed = base * (1 + overhead_pct / 100.0)
                        best_label = b.get("visit_name")
                        best_amount = round(billed, 2)
                        best_confidence = "MEDIUM"
                        if b.get("is_autopaid", False):
                            note_str = "autopaid"
                        else:
                            note_str = "unbilled"
                        break

            result.append({
                "activity_id": a_id,
                "cta_visit_label": best_label,
                "cta_amount": best_amount,
                "match_confidence": best_confidence,
                "notes": note_str if not inv else None,
            })

    # import json
    # print("\nactivity_to_cta\n", json.dumps(result, indent=2))
    return result


def build_entity_scope(study_key: str, study_meta: dict,invoice_to_payment: list[dict],payment_to_remittance: list[dict],activity_index: dict) -> list[dict]:
    """
    Build the entity_scope array that maps every entity to its study/site/investigator
    """
    meta = study_meta[study_key]
    study_id = meta["study_id"]
    site_id = meta["site_id"]
    investigator = meta["investigator"]
    seen = set()
    result = []

    def _add(entity_type, entity_id):
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            result.append({
                "entity_type": entity_type,
                "entity_id": entity_id,
                "study_id": study_id,
                "site_id": site_id,
                "investigator": investigator,
            })

    for entry in invoice_to_payment:
        _add("invoice", entry["invoice_id"])
        for pid in entry.get("payment_ids", []):
            _add("payment", pid)

    for entry in payment_to_remittance:
        _add("payment", entry["payment_id"])
        for rid in entry.get("remittance_ids", []):
            _add("remittance", rid)

    for subj, activities in activity_index.items():
        for a_id, visit, a_date in activities:
            _add("activity", a_id)

    return result
