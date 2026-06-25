import json
from domain.models import Invoice, Remittance, Deposit
from utils.financial import amounts_match, to_cents, from_cents
from services.chains import (
    compute_avg_days_to_payment,
    get_all_activities,
    build_invoice_to_activities,
    build_remittance_to_activities,
    build_activity_to_cta,
    build_entity_scope,
)
from utils.logger import get_logger

logger = get_logger(__name__)

def generate_reports(study_meta, invoices: list[Invoice], remittances: list[Remittance], deposit_map, inv_results, ap_results, unbilled_results, comms, visit_logs):
    results = {}
    for s_key, meta in study_meta.items():
        # Get study-specific invoices for chain building
        study_invoices = [inv for inv in invoices if inv.study_key == s_key]

        # Get study-specific remittances
        # We route by checking if the remittance explicitly pays an invoice belonging to this study.
        study_inv_ids = {inv.invoice_id for inv in study_invoices}
        study_remittances = []
        for rem in remittances:
            valid_lines_for_study = 0
            invalid_lines_for_study = 0
            
            for line in rem.lines:
                r_inv_id = line.invoice_id
                # Does this invoice exist in this study?
                inv_match = next((i for i in study_invoices if i.invoice_id == r_inv_id), None)
                
                if inv_match:
                    inv_amt_cents = inv_match.total_amount_cents
                    line_gross_cents = line.gross_amount_cents
                    line_paid_cents = line.amount_paid_cents
                    expected_settled_cents = int(round(inv_amt_cents * (1 - meta.holdback)))
                    
                    if amounts_match(inv_amt_cents, line_gross_cents) or amounts_match(expected_settled_cents, line_paid_cents):
                        valid_lines_for_study += 1
                    else:
                        invalid_lines_for_study += 1
                else:
                    invalid_lines_for_study += 1
            if valid_lines_for_study > 0 and invalid_lines_for_study == 0:
                study_remittances.append(rem)
            elif valid_lines_for_study > 0 and invalid_lines_for_study > 0:
                logger.warning(f"Remittance {rem.remittance_id} pays invoices across multiple studies. Needs splitting.")
                study_remittances.append(rem)

        # Build payment_to_remittance from deposit map
        payment_to_remittance = []
        ap_r = ap_results.get(s_key)
        for txn_id, dep_info in deposit_map.items():
            r_id = dep_info.remittance_id
            if dep_info.study_key == s_key:
                notes = "likely autopaid" if ap_r and txn_id in ap_r.matched_deposits else None
                payment_to_remittance.append({
                    "payment_id": txn_id,
                    "remittance_ids": [r_id] if r_id else [],
                    "notes": notes,
                })

        # Build the detailed chain arrays
        activity_index = get_all_activities(
            visit_logs, s_key, study_meta
        )
        inv_to_act = build_invoice_to_activities(study_invoices, activity_index)
        rem_to_act = build_remittance_to_activities(study_remittances, inv_to_act, s_key, study_meta)
        act_to_cta = build_activity_to_cta(activity_index, inv_to_act, study_invoices, s_key, study_meta)
        inv_r = inv_results.get(s_key)
        invoice_to_payment = [i.to_dict() for i in inv_r.invoice_to_payment] if inv_r and inv_r.invoice_to_payment else []
        entity_scope = build_entity_scope(s_key, study_meta, invoice_to_payment, payment_to_remittance, activity_index)
        day_pairs = inv_results[s_key].payment_day_pairs if s_key in inv_results else []
        avg_days = compute_avg_days_to_payment(day_pairs)

        # Compute total_collected from deposit map by summing cents first
        total_collected_cents = sum(
            info.amount_cents for info in deposit_map.values()
            if info.study_key == s_key
        )
        total_collected = from_cents(total_collected_cents)

        # Merge dashboard values
        inv_r = inv_results.get(s_key)
        ap_r = ap_results.get(s_key)
        ub_r = unbilled_results.get(s_key)

        results[s_key] = {
            "chains": {
                "study_id": meta.study_id,
                "site_id": meta.site_id,
                "investigator": meta.investigator,
                "payment_to_remittance": payment_to_remittance,
                "invoice_to_payment": invoice_to_payment,
                "invoice_to_activities": inv_to_act,
                "remittance_to_activities": rem_to_act,
                "activity_to_cta": act_to_cta,
                "entity_scope": entity_scope,
            },
            "dashboard": {
                "study_id": meta.study_id,
                "site_id": meta.site_id,
                "investigator": meta.investigator,
                "total_billed": from_cents((inv_r.billed_total_cents if inv_r else 0) + (ap_r.billed_total_cents if ap_r else 0)),
                "total_collected": total_collected,
                "outstanding_ar": from_cents(inv_r.outstanding_ar_cents if inv_r else 0),
                "holdback_withheld": from_cents(inv_r.holdback_withheld_cents if inv_r else 0),
                "unbilled_estimate": ub_r.unbilled_estimate if ub_r else 0.0,
                "exceptions_count": ap_r.exceptions_count if ap_r else 0,
                "avg_days_to_payment": avg_days,
            },
            "invoices": [i.to_dict() for i in study_invoices],
            "remittances": [r.to_dict() for r in study_remittances],
            "unbilled": ub_r.unbilled if ub_r else [],
            "unpaid": ([u.to_dict() for u in inv_r.unpaid] if inv_r else []) + ([u.to_dict() for u in ap_r.unpaid] if ap_r else []),
            "comms": [c.to_dict() for c in comms if c.study_key == s_key],
        }
    return results
