from domain.models import VisitLog, UnbilledResult, Invoice

def normalize_realtime(study_key: str, data: list[dict]) -> list[VisitLog]:
    return [
        VisitLog(
            study_key=study_key,
            subject_id=row.get("SubjectID", ""),
            visit_name=row.get("VisitName", ""),
            source_system="RealTime CTMS",
            activity_id=f"RT-{row.get('SubjectID', '')}-{i}",
            status=row.get("VisitStatus", ""),
            date=row.get("VisitDate", ""),
        )
        for i, row in enumerate(data)
    ]

def normalize_crio(study_key: str, data: list[dict]) -> list[VisitLog]:
    return [
        VisitLog(
            study_key=study_key,
            subject_id=row.get("patient_id", ""),
            visit_name=row.get("visit_name", ""),
            source_system="CRIO CTMS",
            activity_id=row.get("activity_ref", f"CRIO-{row.get('patient_id', '')}"),
            status="Completed", # CRIO implicitly complete in this dataset
            date=row.get("service_date", ""),
        )
        for row in data
    ]

def normalize_clinical_conductor(study_key: str, data: list[dict]) -> list[VisitLog]:
    return [
        VisitLog(
            study_key=study_key,
            subject_id=row.get("Subject", ""),
            visit_name=row.get("ProtocolVisit", ""),
            source_system="Clinical Conductor",
            activity_id=f"CC-{row.get('Subject', '')}-{i}",
            status=row.get("Status", ""),
            date=row.get("VisitDate", ""),
        )
        for i, row in enumerate(data)
    ]

def estimate_visit_amount(visit_name: str, cta_budget: list, overhead_pct: float) -> float:
    """
    Look up the contracted amount for a visit from the CTA budget.
    Returns:
       >0 : The estimated amount (base + overhead)
       -1 : The visit is explicitly autopaid (skip invoicing)
        0 : The visit was not found in the budget (vocabulary mismatch)
    """
    visit_lower = visit_name.lower()
    for entry in cta_budget:
        entry_name = entry.visit_name.lower()
        if entry_name in visit_lower or visit_lower in entry_name:
            if entry.is_autopaid: 
                return -1.0
            base = entry.amount_cents / 100.0
            return base * (1 + overhead_pct / 100.0)
    return 0.0

def detect_unbilled(visit_logs: list[VisitLog], invoices: list[Invoice], study_meta: dict) -> dict[str, UnbilledResult]:
    """
    Detect completed CTMS visits that were never invoiced.
    """
    results = {sk: UnbilledResult(unbilled=[], unbilled_estimate=0.0) for sk in study_meta}

    # Pre-group invoices by study_key
    study_invoices_map = {sk: [] for sk in study_meta}
    for inv in invoices:
        sk = inv.study_key
        if sk:
            study_invoices_map[sk].append(inv)

    for visit in visit_logs:
        if visit.status != "Complete" and visit.status != "Completed":
            continue
            
        study_key = visit.study_key
        meta = study_meta.get(study_key)
        if not meta:
            continue

        has_invoice = False
        for inv in study_invoices_map[study_key]:
            if inv.subject_id == visit.subject_id:
                v_name = visit.visit_name.lower()
                if any(v_name in item.description.lower() for item in inv.line_items):
                    has_invoice = True
                    break

        if not has_invoice:
            est_amt = estimate_visit_amount(visit.visit_name, meta.budget, meta.overhead)
            
            # If the visit is designated as autopaid, we do NOT expect an invoice
            if est_amt < 0:
                continue
            
            results[study_key].unbilled.append({
                "subject_id": visit.subject_id,
                "evidence": f"{visit.source_system} log shows {visit.visit_name} completed, no invoice",
                "proposed_visit_label": visit.visit_name,
                "estimated_amount": est_amt,
                "cta_basis": (f"Procedure-level + {meta.overhead:.0f}% overhead" if est_amt > 0 else "unknown"),
                "confidence": "HIGH" if est_amt > 0 else "LOW",
            })
            
            if est_amt > 0:
                results[study_key].unbilled_estimate += est_amt
                
    return results
