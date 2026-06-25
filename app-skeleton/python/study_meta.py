"""
study_meta.py — CTA metadata construction for the reconciliation engine.

Builds study metadata dictionaries from parsed CTA documents, including
sponsor keywords, budget lines, holdback/overhead rates, and autopayer info.
"""
import re
import json

def build_sponsor_keywords(sponsor_name: str) -> list[str]:
    """
    Extract meaningful keywords from a sponsor name for fuzzy matching.
    """
    noise = {
        "therapeutics", "biosciences", "pharma", "inc", "llc",
        "ltd", "corp", "corporation", "laboratories",
    }
    return [
        k.lower()
        for k in sponsor_name.replace(",", "").replace(".", "").split()
        if len(k) > 3 and k.lower() not in noise
    ]


def _cta_sort_key(cta: dict) -> int:
    p = cta.get("protocol_name", "").lower()
    if "horizon" in p: # MRD-204-017 study
        return 1
    if "ascend" in p: # VTX-330-201 study
        return 2
    if "northstar" in p: # CLX-115-300 study
        return 3
    return 99


def build_study_meta(items: list[dict]) -> tuple[dict, list[str]]:
    """
    Build study metadata from CTA documents.
    Args:
        items: list of all parsed document JSON objects
    Returns:
        (study_meta, study_key_order) where study_meta maps
        study keys like 'study-01-horizon' to metadata dicts.
    """
    ctas = [i for i in items if i.get("type", "").upper() == "CTA"]
    ctas.sort(key=_cta_sort_key)
    
    study_meta = {}
    study_key_order = []

    for idx, cta in enumerate(ctas, start=1):
        st_id = cta.get("study_id", None)
        proto_name = cta.get("protocol_name", "").strip().lower()
        s_key = f"study-{idx:02d}-{proto_name}"
        sponsor = cta.get("sponsor", "")
        keywords = build_sponsor_keywords(sponsor)

        study_meta[s_key] = {
            "study_id": st_id,
            "site_id": cta.get("site_id", None),
            "investigator": cta.get("investigator", None),
            "sponsor": sponsor,
            "keywords": keywords,
            "holdback": float(cta.get("holdback_percent", 0.0)) / 100.0,
            # TODO: Change Overhead to percetange as well
            "overhead": float(cta.get("overhead_percent", 0.0)),
            "budget": cta.get("budget", []),
            "site_fees": cta.get("site_fees", []),
            "effective_date": cta.get("effective_date", ""),
            "autopayer_system": cta.get("autopayer_system"),
            "net_days": cta.get("net_days", 0),
        }
        study_key_order.append(s_key)
    # print(json.dumps(study_meta, indent=4))
    return study_meta, study_key_order
