from domain.models import Invoice, StudyMeta
from utils.financial import to_cents, amounts_match
from utils.logger import get_logger

logger = get_logger(__name__)

def _invoice_amounts_match_study(inv: Invoice, meta: StudyMeta) -> bool:
    """Check if the invoice amounts match the given CTA budget or site fees
    This could be hard to check if not direct correspondence
    """
    inv_amts_cents = [item.amount_cents for item in inv.line_items]
    if not inv_amts_cents and inv.total_amount_cents:
        inv_amts_cents = [inv.total_amount_cents]
    if not inv_amts_cents:
        return False
    overhead = meta.overhead
    
    valid_amounts_cents = set()
    for b in meta.budget:
        base_cents = b.amount_cents
        valid_amounts_cents.add(base_cents)
        # Overhead calculation: base_cents + (base_cents * overhead / 100)
        overhead_cents = int(round(base_cents * (1 + overhead / 100.0)))
        valid_amounts_cents.add(overhead_cents)
        
    for sf in meta.site_fees:
        base_cents = sf.amount_cents
        valid_amounts_cents.add(base_cents)
        overhead_cents = int(round(base_cents * (1 + overhead / 100.0)))
        valid_amounts_cents.add(overhead_cents)
        
    # We say it matches if AT LEAST ONE line item matches a known amount
    for amt_cents in inv_amts_cents:
        if any(amounts_match(amt_cents, v_cents) for v_cents in valid_amounts_cents):
            return True      
    return False

def find_study_key(inv: Invoice, study_meta: dict[str, StudyMeta]) -> str | None:
    """
    Dynamically resolve a study key for a document (invoice, comm, etc.).
    Strategy:
      1. Direct study_id match, corroborated by payer keywords and DOLLAR AMOUNTS.
         If both the payer and the amounts mathematically match a *different* study,
         we flag it as a misfile and route it correctly.
      2. Fallback to payer + amount match.
      3. Weak fallback to payer only.
    """
    test_study_id = inv.study_id
    payer = (inv.payer or "").lower()
    direct_match = None
    if test_study_id:
        for s_key, meta in study_meta.items():
            if meta.study_id == test_study_id:
                direct_match = s_key
                break
        ## If both payer and amount corroborate the study_id, return immediately
        if direct_match:
            direct_meta = study_meta[direct_match]
            payer_matches_direct = any(kw in payer for kw in direct_meta.keywords)
            amount_matches_direct = _invoice_amounts_match_study(inv, direct_meta)
            
            if payer_matches_direct and amount_matches_direct:
                return direct_match    
            ## Neither corroborates (probably misfile, loop through all CTAs)
            if not payer_matches_direct and not amount_matches_direct:
                for s_key, meta in study_meta.items():
                    if s_key == direct_match:
                        continue
                    payer_matches_other = any(kw in payer for kw in meta.keywords) if meta.keywords else False
                    amount_matches_other = _invoice_amounts_match_study(inv, meta)
                    if payer_matches_other and amount_matches_other:
                        logger.error(f"MISFILED Invoice {inv.invoice_id} stamped with study {test_study_id} but amounts/payer match study {meta.study_id}")
                        return s_key

    # Strong fallback: match by payer and amount
    for s_key, meta in study_meta.items():
        payer_matches = any(kw in payer for kw in meta.keywords) if meta.keywords else False
        if payer_matches and _invoice_amounts_match_study(inv, meta):
            return s_key
    # Weak fallback: match just by payer
    for s_key, meta in study_meta.items():
        if payer and any(kw in payer for kw in meta.keywords):
            return s_key
    # Matching on study_id without evidence (could be flagged for user review)
    if direct_match:
        return direct_match
    return None
