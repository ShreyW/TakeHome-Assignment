"""
matcher.py — Core matching / reconciliation logic.

Handles:
  - Resolving invoices to studies
  - Mapping bank deposits to studies and remittances
  - Matching invoices to payments with holdback logic
  - Matching autopays to deposits with exception detection
  - Detecting unbilled visits from CTMS data
"""
from datetime import datetime

# ──────────────────────────────────────────────────────────
#  Study resolution
# ──────────────────────────────────────────────────────────

def _invoice_amounts_match_study(inv: dict, meta: dict) -> bool:
    """Check if the invoice amounts match the given CTA budget or site fees
    This could be hard to check if not direct correspondence
    """
    inv_amts = [float(item.get("amount", 0)) for item in inv.get("line_items", [])]
    if not inv_amts and inv.get("total_amount"):
        inv_amts = [float(inv["total_amount"])]
    if not inv_amts:
        return False
    overhead = float(meta.get("overhead", 0.0))
    
    valid_amounts = set()
    for b in meta.get("budget", []):
        base = float(b["amount"])
        valid_amounts.add(base)
        valid_amounts.add(round(base * (1 + overhead / 100.0), 2))
        
    for sf in meta.get("site_fees", []):
        base = float(sf["amount"])
        valid_amounts.add(base)
        valid_amounts.add(round(base * (1 + overhead / 100.0), 2)) 
    # We say it matches if AT LEAST ONE line item matches a known amount
    for amt in inv_amts:
        if any(abs(amt - v) < 0.01 for v in valid_amounts):
            return True      
    return False

def find_study_key(inv: dict, study_meta: dict) -> str | None:
    """
    Dynamically resolve a study key for a document (invoice, comm, etc.).
    Strategy:
      1. Direct study_id match, corroborated by payer keywords and DOLLAR AMOUNTS.
         If both the payer and the amounts mathematically match a *different* study,
         we flag it as a misfile and route it correctly.
      2. Fallback to payer + amount match.
      3. Weak fallback to payer only.
    """
    test_study_id = inv.get("study_id")
    payer = (inv.get("payer") or "").lower()
    direct_match = None
    if test_study_id:
        for s_key, meta in study_meta.items():
            if meta["study_id"] == test_study_id:
                direct_match = s_key
                break
        ## If both payer and amount corroborate the study_id, return immediately
        if direct_match:
            direct_meta = study_meta[direct_match]
            payer_matches_direct = any(kw in payer for kw in direct_meta["keywords"])
            amount_matches_direct = _invoice_amounts_match_study(inv, direct_meta)
            
            if payer_matches_direct and amount_matches_direct:
                return direct_match    
            ## Neither corroborates (probably misfile, loop through all CTAs)
            if not payer_matches_direct and not amount_matches_direct:
                for s_key, meta in study_meta.items():
                    if s_key == direct_match:
                        continue
                    payer_matches_other = any(kw in payer for kw in meta["keywords"]) if meta["keywords"] else False
                    amount_matches_other = _invoice_amounts_match_study(inv, meta)
                    if payer_matches_other and amount_matches_other:
                        print(f"ERROR: MISFILED Invoice {inv.get('invoice_id')} stamped with study {test_study_id} but amounts/payer match study {meta['study_id']}")
                        return s_key

    # Strong fallback: match by payer and amount
    for s_key, meta in study_meta.items():
        payer_matches = any(kw in payer for kw in meta["keywords"]) if meta["keywords"] else False
        if payer_matches and _invoice_amounts_match_study(inv, meta):
            return s_key
    # Weak fallback: match just by payer
    for s_key, meta in study_meta.items():
        if payer and any(kw in payer for kw in meta["keywords"]):
            return s_key
    # Matching on study_id without evidence (could be flagged for user review)
    if direct_match:
        return direct_match
    return None

# ──────────────────────────────────────────────────────────
#  Deposit --> Study and Remittance mapping
# ──────────────────────────────────────────────────────────

def _parse_date(s: str):
    """Parse YYYY-MM-DD to a datetime, or return None"""
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None

def match_deposits(deposits: list[dict], study_meta: dict,
                   reg_lr: list[dict], reg_ramp: list[dict],
                   remittances: list[dict], invoices: list[dict]) -> dict:
    """
    Map bank deposits to studies and remittances
    ## ASSUMPTION: Non-sponsor deposits are skipped entirely to avoid
    inflating total_collected with unrelated revenue
    """
    result = {}
    used_lr_refs = set()
    used_ramp_refs = set()
    used_rems = set()

    # Build invoice_id --> (study_keys amount) map (handles duplicate IDs across studies)
    inv_to_studies = {}
    for inv in invoices:
        i_id = inv.get("invoice_id")
        amt = float(inv.get("total_amount", 0))
        if i_id:
            sk = find_study_key(inv, study_meta)
            if sk:
                if i_id not in inv_to_studies:
                    inv_to_studies[i_id] = {}
                inv_to_studies[i_id][sk] = amt
    # for k, v in inv_to_studies.items():
    #     print(k, v)
    ## ASSUMPTION: Currency is always USD, same account ID
    for dep in deposits:
        amt = float(dep["amount"])
        dep_name = dep["name"].lower()
        dep_date_str = dep.get("date", "")
        dep_date = _parse_date(dep_date_str)
        txn_id = dep["transaction_id"]

        # 1. Match to a remittance register entry by exact amount AND date proximity (< 5 days)
        ## 1.1 Check in LR registery
        remittance_ref = None
        for lr in reg_lr:
            ref = lr["Reference"]
            if ref not in used_lr_refs and abs(float(lr["Amount"]) - amt) < 0.01:
                lr_date = _parse_date(lr.get("PostedDate", ""))
                if dep_date and lr_date and abs((dep_date - lr_date).days) <= 5:
                    remittance_ref = ref
                    used_lr_refs.add(ref)
                    break
        ## 1.2 Check in ramp registery
        if not remittance_ref:
            for rp in reg_ramp:
                ref = rp["RampRef"]
                if ref not in used_ramp_refs and abs(float(rp["Amount"]) - amt) < 0.01:
                    rp_date = _parse_date(rp.get("Date", ""))
                    if dep_date and rp_date and abs((dep_date - rp_date).days) <= 5:
                        remittance_ref = ref
                        used_ramp_refs.add(ref)
                        break
        # 1.3 Match deposit directly to a Remittance parsed PDF (based on amount and date)
        ## TODO: Used_rems needs a unique key
        matched_rem = None
        for rem in remittances:
            r_id = rem.get("remittance_id")
            if r_id in used_rems:
                continue
            r_amt = float(rem.get("total_paid") or rem.get("amount") or 0)
            if abs(r_amt - amt) < 0.01:
                r_date_str = rem.get("date") or rem.get("payment_date") or ""
                r_date = _parse_date(r_date_str)
                if dep_date and r_date and abs((dep_date - r_date).days) <= 5:
                    matched_rem = rem
                    if r_id:
                        used_rems.add(r_id)
                    break
        # 2. Determine study_key for the payment by matching invoice_id in remittance to inv_to_studies map
        study_key = None  
        if matched_rem:
            candidate_studies = {}
            for line in matched_rem.get("lines", []):
                inv_id = line.get("invoice_id")
                line_amt = float(line.get("amount_paid", 0))
                if inv_id in inv_to_studies:
                    for sk, expected_amt in inv_to_studies[inv_id].items():
                        expected_settled = expected_amt * (1 - study_meta[sk].get("holdback", 0))        
                        if abs(line_amt - expected_amt) < 0.01 or abs(line_amt - expected_settled) < 0.01:
                            candidate_studies[sk] = candidate_studies.get(sk, 0) + 1                
            if len(candidate_studies) == 1:
                study_key = list(candidate_studies.keys())[0]
            else:
                rem_payor = matched_rem.get("payor", "").lower()
                for sk, meta in study_meta.items():
                    if any(kw in rem_payor for kw in meta["keywords"]):
                        study_key = sk
                        break
        
        # Fallback if no remittance
        if not study_key:
            # Try to match deposit amount against known invoice amounts
            for inv_id, sk_amts in inv_to_studies.items():
                for sk, expected_amt in sk_amts.items():
                    expected_settled = expected_amt * (1 - study_meta[sk].get("holdback", 0))
                    if abs(amt - expected_amt) < 0.01 or abs(amt - expected_settled) < 0.01:
                        if any(kw in dep_name for kw in study_meta[sk]["keywords"]):
                            study_key = sk
                            break
                if study_key:
                    break
        if not study_key:
            # print("HERERE", dep_name)
            possible_studies = []
            for s_key, meta in study_meta.items():
                if any(kw in dep_name for kw in meta["keywords"]):
                    possible_studies.append(s_key)
            if len(possible_studies) == 1:
                study_key = possible_studies[0]


        if not study_key:
            continue
        # ASSUMPTION: Reject deposits from before the CTA's effective date
        eff_date = _parse_date(study_meta[study_key].get("effective_date", ""))
        if eff_date and dep_date and dep_date < eff_date:
            # print("WARNING: EFFECTIVE DATE PAYMENT SKIPPED", amt, dep_name, dep_date_str, study_key)
            continue
        # No remittance, no matched PDF, and no autopayer system means this is an old deposit
        if not remittance_ref and not matched_rem and not study_meta[study_key].get("autopayer_system"):
            # print("WARNING: PAYMENT SKIPPED DUE TO NO REMITTANCE OR PDF", amt, dep_name, dep_date_str, study_key)
            continue

        result[txn_id] = {
            "study_key": study_key,
            "amount": amt,
            "date": dep_date_str,
            "remittance_ref": remittance_ref,
            "remittance_id": matched_rem.get("remittance_id") if matched_rem else None,
            "remittance_lines": matched_rem.get("lines", []) if matched_rem else []
        }
    # print(len(result))
    ## PRINT RESULTS CLEANLY
    # for k, v in result.items():
    #     print(f"txn_id={k} | {v}")
    return result


# ──────────────────────────────────────────────────────────
#  Invoice -> Payment matching
# ──────────────────────────────────────────────────────────

def _is_site_fee(inv: dict, study_key: str, study_meta: dict) -> bool:
    """Determine if an invoice is for a site fee"""
    meta = study_meta[study_key]
    amt = float(inv.get("total_amount", 0))

    if inv.get("line_items"):
        for item in inv["line_items"]:
            desc = item.get("description", "").lower()
            item_amt = float(item.get("amount", 0))
            for sf in meta.get("site_fees", []):
                sf_name = sf.get("name", "").lower()
                if (sf_name and sf_name in desc) or \
                   (sf.get("amount") and abs(item_amt - float(sf["amount"])) < 1.0):
                    return True
    elif any(sf.get("amount") and abs(amt - float(sf["amount"])) < 1.0
             for sf in meta.get("site_fees", [])):
        return True

    return False


def _is_comm_unpaid(inv_id: str, comms: list[dict]) -> bool:
    """Check if the latest comm flagging this invoice marks it as unpaid."""
    relevant_comms = []
    for comm in comms:
        mentions = comm.get("mentions_invoices", [])
        if not isinstance(mentions, list):
            mentions = []
        c_text = comm.get("content_summary", "").lower()
        
        if inv_id in mentions or inv_id.lower() in c_text:
            relevant_comms.append(comm)
            
    if not relevant_comms:
        return False
    relevant_comms.sort(key=lambda x: x.get("date", "0000-00-00"), reverse=True)
    latest = relevant_comms[0]
    status = latest.get("status_update", "").lower()
    c_text = latest.get("content_summary", "").lower()
    unpaid_terms = ["unpaid", "hold", "dispute", "not authorize", "pending"]
    if any(t in status for t in unpaid_terms) or any(t in c_text for t in unpaid_terms):
        return True
        
    return False


def match_invoices(invoices: list[dict], deposit_map: dict, study_meta: dict, study_key_order: list[str],
                   comms: list[dict]) -> dict:
    """
    Match invoices to bank deposits and compute their payment status
    """

    available_deposits = []
    for txn_id, info in deposit_map.items():
        available_deposits.append({"transaction_id": txn_id,**info,})

    used_lines = set()
    used_direct_wires = set()
    results = {study_key: {
        "invoice_to_payment": [],
        "unpaid": [],
        "billed_total": 0.0,
        "outstanding_ar": 0.0,
        "holdback_withheld": 0.0,
        "payment_day_pairs": [],
    } for study_key in study_meta}

    for inv in invoices:
        inv_id = inv.get("invoice_id", None)
        if not inv_id:
            print(f"ERROR: Invoice {inv} has no invoice_id.")
            continue
        amt = float(inv.get("total_amount", 0))
        study_key = find_study_key(inv, study_meta)
        if not study_key:
            print(f"ERROR: Cannot resolve study for invoice {inv_id}. Manual Review.")
            continue
        results[study_key]["billed_total"] += amt

        # TODO: Handle comms 
        is_unpaid = _is_comm_unpaid(inv_id, comms)
        # TODO: Hard to decipher if an invoice has site fees
        site_fee = _is_site_fee(inv, study_key, study_meta)
        # print(study_key, inv.get("invoice_id"), site_fee, inv.get("total_amount"))
        holdback = study_meta[study_key]["holdback"] if not site_fee else 0.0

        # Try to match a bank deposit
        matched_deposit = None
        remittance_invoice_line = None
        # Check if the invoice is bundled in any deposit's remittance lines
        for dep in available_deposits:
            if dep["study_key"] == study_key:
                for idx, line in enumerate(dep.get("remittance_lines", [])):
                    line_key = f'{dep["transaction_id"]}_{idx}'
                    if line_key in used_lines:
                        continue
                        
                    line_amt = float(line.get("amount_paid", 0))
                    expected_settled = amt * (1 - holdback)
                    if line.get("invoice_id") == inv_id:
                        if abs(line_amt - expected_settled) < 0.01 or abs(line_amt - amt) < 0.01:
                            matched_deposit = dep
                            remittance_invoice_line = line
                            used_lines.add(line_key)
                            break
                # single invoice wires (no remittance PDF)
                if not matched_deposit and not dep.get("remittance_lines"):
                    if dep["transaction_id"] not in used_direct_wires:
                        dep_amt = float(dep["amount"])
                        expected_settled = amt * (1 - holdback)
                        if abs(dep_amt - amt) < 0.01 or abs(dep_amt - expected_settled) < 0.01:
                            matched_deposit = dep
                            remittance_invoice_line = {"amount_paid": dep_amt}
                            used_direct_wires.add(dep["transaction_id"])
                            break
            if matched_deposit:
                break
                
        if matched_deposit and not is_unpaid:
            settled_amt = float(remittance_invoice_line.get("amount_paid", 0))
            holdback_amount = amt - settled_amt if settled_amt < amt else 0.0
            r_id_found = matched_deposit.get("remittance_id")
            
            notes = f"Paid via remittance {r_id_found}" if r_id_found else "Paid via direct wire"
            if holdback_amount > 0:
                notes = f"Withheld ${holdback_amount:.2f} (via remittance {r_id_found})" if r_id_found else f"Withheld ${holdback_amount:.2f} (direct wire)"
            
            results[study_key]["invoice_to_payment"].append({
                "invoice_id": inv_id,
                "payment_ids": [matched_deposit["transaction_id"]],
                "invoice_amount": amt,
                "amount_settled": settled_amt,
                "status": "paid",
                "notes": notes,
            })
            results[study_key]["holdback_withheld"] += holdback_amount
            inv_date = inv.get("invoice_date") 
            pay_date = matched_deposit.get("date")
            if inv_date and pay_date:
                # print(study_key,inv_id, amt, matched_deposit, inv_date, pay_date)
                results[study_key]["payment_day_pairs"].append((inv_date, pay_date))
        elif is_unpaid:
            results[study_key]["unpaid"].append({
                "ref_type": "invoice",
                "ref_id": inv_id,
                "amount_expected": amt,
                "age_days": None,
                "reason": "sent_not_paid",
                "evidence": "comms confirm unpaid",
                "confidence": "HIGH",
            })
            
            results[study_key]["invoice_to_payment"].append({
                "invoice_id": inv_id,
                "payment_ids": [],
                "invoice_amount": amt,
                "amount_settled": 0.0,
                "status": "unpaid",
                "notes": "flagged unpaid in comms",
            })
            
            # print("HERE", study_key,inv_id, amt)
            results[study_key]["outstanding_ar"] += amt
        else:
            # Invoice did not match any deposit and not in comms, no evidence of payment, flag as unpaid
            results[study_key]["invoice_to_payment"].append({
                "invoice_id": inv_id,
                "payment_ids": [],
                "invoice_amount": amt,
                "amount_settled": 0.0,
                "status": "unpaid",
                "notes": "no matching deposit found",
            })
            
            inv_date = inv.get("invoice_date")
            age_days = (datetime.now() - _parse_date(inv_date)).days if inv_date and _parse_date(inv_date) else None
            results[study_key]["unpaid"].append({
                "ref_type": "invoice",
                "ref_id": inv_id,
                "amount_expected": amt,
                "age_days": age_days,
                "reason": "no_payment_found",
                "evidence": "missing from bank feed",
                "confidence": "MEDIUM",
            })
            results[study_key]["outstanding_ar"] += amt

    return results

#  Autopay ->Deposit matching
def match_autopays(reg_eclin: list[dict], deposit_map: dict, study_meta: dict) -> dict:
    available_deposits = []
    for txn_id, info in deposit_map.items():
        available_deposits.append({"transaction_id": txn_id, **info})

    used_deposits = set()
    results = {study_key: {
        "billed_total": 0.0,
        "unpaid": [],
        "exceptions_count": 0,
        "unmatched_credits": [],
    } for study_key in study_meta}

    # Gather events per study (Queue)
    study_events = {study_key: [] for study_key in study_meta}

    for ap in reg_eclin:
        amt = float(ap["ScheduledAmount"])
        subject = ap.get("SubjectID", "")
        service_date = _parse_date(ap.get("ServiceDate", ""))
        ap_visit = ap.get("Visit", "").lower()

        # Route by matching visit name and amount to CTA budget
        ap_study_key = None
        for s_key, meta in study_meta.items():
            sys = meta.get("autopayer_system", None)            
            for entry in meta.get("budget", []):
                is_autopaid = entry.get("is_autopaid", False)
                if not sys and not is_autopaid:
                    continue
                v_name = entry.get("visit_name", "").lower()
                expected_amt = float(entry.get("amount", 0)) * (1 + meta.get("overhead", 0) / 100.0)
                if (v_name in ap_visit or ap_visit in v_name) and abs(expected_amt - amt) < 0.01:
                    ap_study_key = s_key
                    break         
            if ap_study_key:
                break
        if not ap_study_key or ap_study_key not in results:
            print("Could not find study id for autopay: ", ap)
            continue

        results[ap_study_key]["billed_total"] += amt  # type: ignore
        
        study_events[ap_study_key].append({
            "type": "debit",
            "date": service_date,
            "amt": amt,
            "ap": ap
        })
    for dep in available_deposits:
        ## ASSUMPTION: Autopay elements don't have a remittance
        if dep.get("remittance_ref") or dep.get("remittance_id"):
            continue
        dep_study_key = dep.get("study_key", "")
        if dep_study_key in study_events:
            dep_date = _parse_date(dep["date"])
            study_events[dep_study_key].append({
                "type": "credit",
                "date": dep_date,
                "amt": dep["amount"],
                "dep": dep
            })
    for s_key, events in study_events.items():
        # Sort chronologically. If dates match, debit comes before credit.
        def event_sort_key(e):
            d = e["date"]
            # Fallback date if None. Debits early (0), Credits late (999999)
            d_val = d.toordinal() if d else (0 if e["type"] == "debit" else 999999)
            return (d_val, 0 if e["type"] == "debit" else 1)
        
        events.sort(key=event_sort_key)
        # print("\n\n\nSTUDY EVENTS FOR ", s_key)
        # for e in events:
        #     print(e)
        # print("\n\n\n")
        pending_debits = []
        for e in events:
            if e["type"] == "debit":
                pending_debits.append(e)
            else:
                credit_amt = e["amt"]
                match_idx = -1    
                # 1. First look for an exact match
                for i, d in enumerate(pending_debits):
                    if abs(d["amt"] - credit_amt) < 0.01:
                        match_idx = i
                        break     
                # 2. If no exact match, fallback to oldest debit > credit (raise exception if there is a match)
                if match_idx == -1:
                    for i, d in enumerate(pending_debits):
                        if d["amt"] > credit_amt + 0.01:
                            match_idx = i
                            break
                if match_idx >= 0:
                    matched_debit = pending_debits.pop(match_idx)
                    used_deposits.add(e["dep"]["transaction_id"])
                    if abs(matched_debit["amt"] - credit_amt) >= 0.01:
                        results[s_key]["exceptions_count"] += 1  # type: ignore
                else:
                    # No pending debit can satisfy this credit, anomalous extra deposit
                    print(e)
                    results[s_key]["exceptions_count"] += 1  # type: ignore
                    results[s_key]["unmatched_credits"].append(e)
        
        for d in pending_debits:
            conf = "HIGH"
            ev = "never deposited"
            if len(results[s_key]["unmatched_credits"]) > 0:
                conf = "LOW"
                ev = "unmatched credits exist in study, possible overpayment or mismatched funds"
            results[s_key]["unpaid"].append({
                "ref_type": "autopay",
                "ref_id": d["ap"]["AutopayID"],
                "amount_expected": d["amt"],
                "age_days": (datetime.now() - d["date"]).days if d["date"] else None,
                "reason": "autopay_no_deposit",
                "evidence": ev,
                "confidence": conf,
            })
    return results


# ──────────────────────────────────────────────────────────
#  Unbilled detection
# ──────────────────────────────────────────────────────────

def estimate_visit_amount(visit_name: str, cta_budget: list[dict], overhead_pct: float) -> float:
    """
    Look up the contracted amount for a visit from the CTA budget.
    Returns:
       >0 : The estimated amount (base + overhead)
       -1.0: The visit is explicitly autopaid (skip invoicing)
        0.0: The visit was not found in the budget (vocabulary mismatch)
    """
    visit_lower = visit_name.lower()
    for entry in cta_budget:
        entry_name = entry.get("visit_name", "").lower()
        if entry_name in visit_lower or visit_lower in entry_name:
            if entry.get("is_autopaid", False): 
                return -1.0
            base = float(entry.get("amount", 0))
            return base * (1 + overhead_pct / 100.0)
    return 0.0

def detect_unbilled(ctms_cc: list[dict], ctms_rt: list[dict], ctms_crio: list[dict], invoices: list[dict], study_meta: dict) -> dict:
    """
    Detect completed CTMS visits that were never invoiced.
    """
    results = {sk: {
        "unbilled": [],
        "unbilled_estimate": 0.0,
    } for sk in study_meta}

    # Pre-group invoices by study_key
    study_invoices_map = {sk: [] for sk in study_meta}
    for inv in invoices:
        sk = find_study_key(inv, study_meta)
        if sk:
            study_invoices_map[sk].append(inv)

    # 1:1 Mapping of Study to CTMS Log
    ctms_mapping = {
        "study-01-horizon": ("RealTime CTMS", ctms_rt),
        "study-02-ascend": ("CRIO CTMS", ctms_crio),
        "study-03-northstar": ("Clinical Conductor", ctms_cc)
    }

    for study_key, (ctms_name, ctms_log) in ctms_mapping.items():           
        meta = study_meta[study_key]
        
        for row in ctms_log:
            if ctms_name == "RealTime CTMS":
                if row.get("VisitStatus") != "Complete":
                    continue
                subject = row.get("SubjectID", "")
                visit_name = row.get("VisitName", "")
            elif ctms_name == "Clinical Conductor":
                if row.get("Status") != "Completed":
                    continue
                subject = row.get("Subject", "")
                visit_name = row.get("ProtocolVisit", "")
            elif ctms_name == "CRIO CTMS":
                subject = row.get("patient_id", "")
                visit_name = row.get("visit_name", "")

            has_invoice = False
            for inv in study_invoices_map[study_key]:
                if inv.get("subject_id") == subject:
                    v_name = visit_name.lower()
                    if any(v_name in item.get("description", "").lower() for item in inv.get("line_items", [])):
                        has_invoice = True
                        # print(f"Billed: Study {study_key} | Subject {subject} | Visit '{visit_name}', Invoice {inv.get('invoice_id')}")
                        break

            if not has_invoice:
                est_amt = estimate_visit_amount(visit_name, meta["budget"], meta.get("overhead", 0))
                
                # If the visit is designated as autopaid, we do NOT expect an invoice
                if est_amt < 0:
                    continue
                
                # If est_amt == 0.0, it means there was a vocabulary mismatch. We still record it!
                # print(f"Unbilled: Study {study_key} | Subject {subject} | Visit '{visit_name}' | Est: {est_amt}")
                results[study_key]["unbilled"].append({
                    "subject_id": subject,
                    "evidence": f"{ctms_name} log shows {visit_name} completed, no invoice",
                    "proposed_visit_label": visit_name,
                    "estimated_amount": est_amt,
                    "cta_basis": (f"Procedure-level + {meta.get('overhead', 0):.0f}% overhead" if est_amt > 0 else "unknown"),
                    "confidence": "HIGH" if est_amt > 0 else "LOW",
                })
                
                if est_amt > 0:
                    results[study_key]["unbilled_estimate"] += est_amt
           
    return results
