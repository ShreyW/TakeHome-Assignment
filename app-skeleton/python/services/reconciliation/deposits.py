from typing import Optional
from datetime import datetime
from utils.financial import to_cents, amounts_match
from domain.models import Invoice, Deposit, Remittance, MatchedDeposit
from utils.logger import get_logger
logger = get_logger(__name__)
def _parse_date(s: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD to a datetime, or return None"""
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None

def match_deposits(deposits: list[Deposit], study_meta: dict,
                   reg_lr: list[dict], reg_ramp: list[dict],
                   remittances: list[Remittance], invoices: list[Invoice]) -> dict[str, MatchedDeposit]:
    """
    Map bank deposits to studies and remittances
    ## ASSUMPTION: Non-sponsor deposits are skipped entirely to avoid
    inflating total_collected with unrelated revenue
    """
    result = {}
    used_lr_refs = set()
    used_ramp_refs = set()
    used_rems = set()

    # Build invoice_id --> (study_keys amount_cents) map (handles duplicate IDs across studies)
    inv_to_studies = {}
    for inv in invoices:
        i_id = inv.invoice_id
        amt_cents = inv.total_amount_cents
        if i_id:
            sk = inv.study_key
            if sk:
                if i_id not in inv_to_studies:
                    inv_to_studies[i_id] = {}
                inv_to_studies[i_id][sk] = amt_cents

    ## ASSUMPTION: Currency is always USD, same account ID
    for dep in deposits:
        amt_cents = dep.amount_cents
        # Keep float for output
        amt_float = amt_cents / 100.0
        dep_name = dep.name.lower()
        dep_date_str = dep.date
        dep_date = _parse_date(dep_date_str)
        txn_id = dep.transaction_id

        # 1. Match to a remittance register entry by exact amount AND date proximity (< 5 days)
        ## 1.1 Check in LR registery
        remittance_ref = None
        for lr in reg_lr:
            ref = lr["Reference"]
            if ref not in used_lr_refs and amounts_match(to_cents(lr["Amount"]), amt_cents):
                lr_date = _parse_date(lr.get("PostedDate", ""))
                if dep_date and lr_date and abs((dep_date - lr_date).days) <= 5:
                    remittance_ref = ref
                    used_lr_refs.add(ref)
                    break
        ## 1.2 Check in ramp registery
        if not remittance_ref:
            for rp in reg_ramp:
                ref = rp["RampRef"]
                if ref not in used_ramp_refs and amounts_match(to_cents(rp["Amount"]), amt_cents):
                    rp_date = _parse_date(rp.get("Date", ""))
                    if dep_date and rp_date and abs((dep_date - rp_date).days) <= 5:
                        remittance_ref = ref
                        used_ramp_refs.add(ref)
                        break
        # 1.3 Match deposit directly to a Remittance parsed PDF (based on amount and date)
        ## TODO: Used_rems needs a unique key
        matched_rem = None
        for rem in remittances:
            r_id = rem.remittance_id
            if r_id in used_rems:
                continue
            r_amt_cents = rem.total_paid_cents
            if amounts_match(r_amt_cents, amt_cents):
                r_date_str = rem.payment_date
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
            for line in matched_rem.lines:
                inv_id = line.invoice_id
                line_amt_cents = line.amount_paid_cents
                if inv_id in inv_to_studies:
                    for sk, expected_amt_cents in inv_to_studies[inv_id].items():
                        expected_settled_cents = int(round(expected_amt_cents * (1 - study_meta[sk].holdback)))        
                        if amounts_match(line_amt_cents, expected_amt_cents) or amounts_match(line_amt_cents, expected_settled_cents):
                            candidate_studies[sk] = candidate_studies.get(sk, 0) + 1                
            if len(candidate_studies) == 1:
                study_key = list(candidate_studies.keys())[0]
            else:
                rem_payor = matched_rem.payor.lower()
                for sk, meta in study_meta.items():
                    if any(kw in rem_payor for kw in meta.keywords):
                        study_key = sk
                        break
        
        # Fallback if no remittance
        if not study_key:
            # Try to match deposit amount against known invoice amounts
            for inv_id, sk_amts in inv_to_studies.items():
                for sk, expected_amt_cents in sk_amts.items():
                    expected_settled_cents = int(round(expected_amt_cents * (1 - study_meta[sk].holdback)))
                    if amounts_match(amt_cents, expected_amt_cents) or amounts_match(amt_cents, expected_settled_cents):
                        if any(kw in dep_name for kw in study_meta[sk].keywords):
                            study_key = sk
                            break
                if study_key:
                    break
        if not study_key:
            # print("HERERE", dep_name)
            possible_studies = []
            for s_key, meta in study_meta.items():
                if any(kw in dep_name for kw in meta.keywords):
                    possible_studies.append(s_key)
            if len(possible_studies) == 1:
                study_key = possible_studies[0]


        if not study_key:
            continue
        # ASSUMPTION: Reject deposits from before the CTA's effective date
        eff_date = _parse_date(study_meta[study_key].effective_date)
        if eff_date and dep_date and dep_date < eff_date:
            # print("WARNING: EFFECTIVE DATE PAYMENT SKIPPED", amt, dep_name, dep_date_str, study_key)
            continue
        # No remittance, no matched PDF, and no autopayer system means this is an old deposit
        if not remittance_ref and not matched_rem and not study_meta[study_key].autopayer_system:
            # print("WARNING: PAYMENT SKIPPED DUE TO NO REMITTANCE OR PDF", amt, dep_name, dep_date_str, study_key)
            continue

        result[txn_id] = MatchedDeposit(
            transaction_id=txn_id,
            study_key=study_key,
            amount_cents=amt_cents,
            date=dep_date_str,
            remittance_ref=remittance_ref,
            remittance_id=matched_rem.remittance_id if matched_rem else None,
            remittance_lines=matched_rem.lines if matched_rem else []
        )
    return result
