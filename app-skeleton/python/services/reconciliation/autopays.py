from datetime import datetime
from utils.financial import to_cents, amounts_match
from domain.models import MatchedDeposit, AutopayMatchResult, UnpaidItem
from utils.logger import get_logger
from .deposits import _parse_date
logger = get_logger(__name__)
def match_autopays(reg_eclin: list[dict], deposit_map: dict[str, MatchedDeposit], study_meta: dict) -> dict[str, AutopayMatchResult]:
    available_deposits = []
    for txn_id, info in deposit_map.items():
        available_deposits.append(info)

    used_deposits = set()
    results = {study_key: AutopayMatchResult(
        billed_total_cents=0,
        unpaid=[],
        exceptions_count=0,
        matched_deposits=[],
    ) for study_key in study_meta}
    unmatched_credits = {study_key: [] for study_key in study_meta}

    # Gather events per study (Queue)
    study_events = {study_key: [] for study_key in study_meta}

    for ap in reg_eclin:
        amt_cents = to_cents(ap["ScheduledAmount"])
        amt_float = float(ap["ScheduledAmount"])
        subject = ap.get("SubjectID", "")
        service_date = _parse_date(ap.get("ServiceDate", ""))
        ap_visit = ap.get("Visit", "").lower()

        # Route by matching visit name and amount to CTA budget
        ap_study_key = None
        for s_key, meta in study_meta.items():
            sys = meta.autopayer_system            
            for entry in meta.budget:
                is_autopaid = entry.is_autopaid
                if not sys and not is_autopaid:
                    continue
                v_name = entry.visit_name.lower()
                expected_amt_cents = int(round(entry.amount_cents * (1 + meta.overhead / 100.0)))
                if (v_name in ap_visit or ap_visit in v_name) and amounts_match(expected_amt_cents, amt_cents):
                    ap_study_key = s_key
                    break         
            if ap_study_key:
                break
        if not ap_study_key or ap_study_key not in results:
            # print("Could not find study id for autopay: ", ap)
            continue

        results[ap_study_key].billed_total_cents += amt_cents
        
        study_events[ap_study_key].append({
            "type": "debit",
            "date": service_date,
            "amt_cents": amt_cents,
            "amt_float": amt_float,
            "ap": ap
        })
    for dep in available_deposits:
        ## ASSUMPTION: Autopay elements don't have a remittance
        if dep.remittance_ref or dep.remittance_id:
            continue
        dep_study_key = dep.study_key
        if dep_study_key in study_events:
            dep_date = _parse_date(dep.date)
            study_events[dep_study_key].append({
                "type": "credit",
                "date": dep_date,
                "amt_cents": dep.amount_cents,
                "amt_float": dep.amount_cents / 100.0,
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
                credit_amt_cents = e["amt_cents"]
                match_idx = -1    
                # 1. First look for an exact match
                for i, d in enumerate(pending_debits):
                    if amounts_match(d["amt_cents"], credit_amt_cents):
                        match_idx = i
                        break     
                # 2. If no exact match, fallback to oldest debit > credit (raise exception if there is a match)
                if match_idx == -1:
                    for i, d in enumerate(pending_debits):
                        if d["amt_cents"] > credit_amt_cents + 1:
                            match_idx = i
                            break
                if match_idx >= 0:
                    matched_debit = pending_debits.pop(match_idx)
                    used_deposits.add(e["dep"].transaction_id)
                    results[s_key].matched_deposits.append(e["dep"].transaction_id)
                    if not amounts_match(matched_debit["amt_cents"], credit_amt_cents):
                        results[s_key].exceptions_count += 1
                else:
                    # No pending debit can satisfy this credit, anomalous extra deposit
                    # print(e)
                    results[s_key].exceptions_count += 1
                    unmatched_credits[s_key].append(e)
        
        for d in pending_debits:
            conf = "HIGH"
            ev = "never deposited"
            if len(unmatched_credits[s_key]) > 0:
                conf = "LOW"
                ev = "unmatched credits exist in study, possible overpayment or mismatched funds"
            results[s_key].unpaid.append(UnpaidItem(
                ref_type="autopay",
                ref_id=d["ap"]["AutopayID"],
                amount_expected=d["amt_float"],
                age_days=(datetime.now() - d["date"]).days if d["date"] else None,
                reason="autopay_no_deposit",
                evidence=ev,
                confidence=conf,
            ))
    return results
