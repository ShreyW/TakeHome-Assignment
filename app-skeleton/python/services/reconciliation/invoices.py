from datetime import datetime
from utils.financial import to_cents, amounts_match
from typing import Any, Optional
from domain.models import Invoice, MatchedDeposit, InvoiceMatchResult, InvoicePaymentMatch, UnpaidItem, Comm
from utils.logger import get_logger
from .deposits import _parse_date

logger = get_logger(__name__)
def _is_site_fee(inv: Invoice, study_key: str, study_meta: dict) -> bool:
    """Determine if an invoice is for a site fee"""
    meta = study_meta[study_key]
    amt_cents = inv.total_amount_cents

    if inv.line_items:
        for item in inv.line_items:
            desc = item.description.lower()
            item_amt_cents = item.amount_cents
            for sf in meta.site_fees:
                sf_name = sf.name.lower()
                if (sf_name and sf_name in desc) or \
                   (sf.amount_cents and amounts_match(item_amt_cents, sf.amount_cents)):
                    return True
    elif any(sf.amount_cents and amounts_match(amt_cents, sf.amount_cents)
             for sf in meta.site_fees):
        return True

    return False


def _is_comm_unpaid(inv_id: str, comms: list[Comm]) -> bool:
    """Check if the latest comm flagging this invoice marks it as unpaid."""
    relevant_comms = []
    for comm in comms:
        mentions = comm.mentions_invoices
        if not isinstance(mentions, list):
            mentions = []
        c_text = comm.content_summary.lower()
        
        if inv_id in mentions or inv_id.lower() in c_text:
            relevant_comms.append(comm)
            
    if not relevant_comms:
        return False
    relevant_comms.sort(key=lambda x: x.date, reverse=True)
    latest = relevant_comms[0]
    status = latest.status_update.lower()
    c_text = latest.content_summary.lower()
    unpaid_terms = ["unpaid", "hold", "dispute", "not authorize", "pending"]
    if any(t in status for t in unpaid_terms) or any(t in c_text for t in unpaid_terms):
        return True
        
    return False


def match_invoices(invoices: list[Invoice], deposit_map: dict[str, MatchedDeposit], study_meta: dict, study_key_order: list[str],
                   comms: list[Comm]) -> dict[str, InvoiceMatchResult]:
    """
    Match invoices to bank deposits and compute their payment status
    """

    available_deposits = list(deposit_map.values())

    used_lines = set()
    used_direct_wires = set()
    results = {study_key: InvoiceMatchResult(
        billed_total_cents=0,
        outstanding_ar_cents=0,
        holdback_withheld_cents=0,
        unpaid=[],
        invoice_to_payment=[],
        payment_day_pairs=[]
    ) for study_key in study_meta}

    for inv in invoices:
        inv_id = inv.invoice_id
        if not inv_id:
            logger.error(f"Invoice {inv} has no invoice_id.")
            continue
        amt_cents = inv.total_amount_cents
        amt_float = amt_cents / 100.0
        study_key = inv.study_key
        if not study_key:
            logger.error(f"Cannot resolve study for invoice {inv_id}. Manual Review.")
            continue
        results[study_key].billed_total_cents += amt_cents

        # TODO: Handle comms 
        is_unpaid = _is_comm_unpaid(inv_id, comms)
        # TODO: Hard to decipher if an invoice has site fees
        site_fee = _is_site_fee(inv, study_key, study_meta)
        # print(study_key, inv.get("invoice_id"), site_fee, inv.get("total_amount"))
        holdback = study_meta[study_key].holdback if not site_fee else 0.0

        # Try to match a bank deposit
        matched_deposit: Optional[MatchedDeposit] = None
        remittance_invoice_line: Any = None
        # Check if the invoice is bundled in any deposit's remittance lines
        for dep in available_deposits:
            if dep.study_key == study_key:
                for idx, line in enumerate(dep.remittance_lines):
                    line_key = f'{dep.transaction_id}_{idx}'
                    if line_key in used_lines:
                        continue
                    line_amt_cents = line.amount_paid_cents
                    expected_settled_cents = int(round(amt_cents * (1 - holdback)))
                    if line.invoice_id == inv_id:
                        if amounts_match(line_amt_cents, expected_settled_cents) or amounts_match(line_amt_cents, amt_cents):
                            matched_deposit = dep
                            remittance_invoice_line = line
                            used_lines.add(line_key)
                            break
                # single invoice wires (no remittance PDF)
                if not matched_deposit and not dep.remittance_lines:
                    if dep.transaction_id not in used_direct_wires:
                        dep_amt_cents = dep.amount_cents
                        expected_settled_cents = int(round(amt_cents * (1 - holdback)))
                        if amounts_match(dep_amt_cents, amt_cents) or amounts_match(dep_amt_cents, expected_settled_cents):
                            matched_deposit = dep
                            remittance_invoice_line = None
                            used_direct_wires.add(dep.transaction_id)
                            break
            if matched_deposit:
                break
                
        inv_date = inv.invoice_date or inv.service_date
        parsed_inv_date = _parse_date(inv_date) if inv_date else None
        age_days = (datetime.now() - parsed_inv_date).days if parsed_inv_date else None

        if matched_deposit and not is_unpaid:
            settled_amt_cents = remittance_invoice_line.amount_paid_cents if remittance_invoice_line else matched_deposit.amount_cents
            holdback_amount_cents = amt_cents - settled_amt_cents if settled_amt_cents < amt_cents else 0
            r_id_found = matched_deposit.remittance_id
            
            notes = f"Paid via remittance {r_id_found}" if r_id_found else "Paid via direct wire"
            if holdback_amount_cents > 0:
                notes = f"Withheld ${(holdback_amount_cents/100.0):.2f} (via remittance {r_id_found})" if r_id_found else f"Withheld ${(holdback_amount_cents/100.0):.2f} (direct wire)"
            
            results[study_key].invoice_to_payment.append(InvoicePaymentMatch(
                invoice_id=inv_id,
                payment_ids=[matched_deposit.transaction_id] if isinstance(matched_deposit, MatchedDeposit) else [matched_deposit["transaction_id"]],
                invoice_amount=amt_float,
                amount_settled=settled_amt_cents / 100.0,
                status="paid",
                notes=notes,
            ))
            results[study_key].holdback_withheld_cents += holdback_amount_cents
            pay_date = matched_deposit.date if isinstance(matched_deposit, MatchedDeposit) else matched_deposit.get("date")
            if inv_date and pay_date:
                results[study_key].payment_day_pairs.append((inv_date, pay_date))
        elif is_unpaid:
            results[study_key].unpaid.append(UnpaidItem(
                ref_type="invoice",
                ref_id=inv_id,
                amount_expected=amt_float,
                age_days=age_days,
                reason="sent_not_paid",
                evidence="comms confirm unpaid",
                confidence="HIGH",
            ))
            
            results[study_key].invoice_to_payment.append(InvoicePaymentMatch(
                invoice_id=inv_id,
                payment_ids=[],
                invoice_amount=amt_float,
                amount_settled=0.0,
                status="unpaid",
                notes="flagged unpaid in comms",
            ))
            
            results[study_key].outstanding_ar_cents += amt_cents
        else:
            # Invoice did not match any deposit and not in comms, no evidence of payment, flag as unpaid
            results[study_key].invoice_to_payment.append(InvoicePaymentMatch(
                invoice_id=inv_id,
                payment_ids=[],
                invoice_amount=amt_float,
                amount_settled=0.0,
                status="unpaid",
                notes="no matching deposit found",
            ))
            
            results[study_key].unpaid.append(UnpaidItem(
                ref_type="invoice",
                ref_id=inv_id,
                amount_expected=amt_float,
                age_days=age_days,
                reason="no_payment_found",
                evidence="missing from bank feed",
                confidence="MEDIUM",
            ))
            results[study_key].outstanding_ar_cents += amt_cents

    return results
