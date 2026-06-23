import os
import glob
import json
import re
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract

DATA_DIR = "../../documents"
CACHE_DIR = "cache"

os.makedirs(CACHE_DIR, exist_ok=True)

def extract_text(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except:
        pass
    
    if len(text.strip()) < 50:
        try:
            pages = convert_from_path(file_path, 300)
            for page in pages:
                text += pytesseract.image_to_string(page) + "\n"
        except:
            pass
            
    return text

def parse_cta(text, filename):
    study_match = re.search(r'\b([A-Z]{3}-\d{3}-\d{3})\b', text)
    study_id = study_match.group(1) if study_match else "UNKNOWN"
    
    inv_match = re.search(r'(?:Principal Investigator|PI|Pl|P!|Investigator)[:\-\s]*([A-Za-z ]+)(?:\n|,| - |$)', text)
    investigator = inv_match.group(1).strip() if inv_match else "Unknown"
    
    site_match = re.search(r'\b(ARP-\d+)\b', text)
    site_id = site_match.group(1) if site_match else "UNKNOWN"
    
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    sponsor = "UNKNOWN"
    if lines:
        first_line = lines[0]
        if first_line.lower().startswith("clinical trial"):
            for line in lines[:5]:
                m = re.search(r'^([A-Za-z\s,.]+?)\s+(?:-|Protocol)', line)
                if m and not m.group(1).lower().startswith("clinical"):
                    sponsor = m.group(1).strip()
                    break
        else:
            sponsor = first_line.split('-')[0].strip()
            
    holdback = 0.0
    hb_match = re.search(r'Holdback\s*(\d+)%', text)
    if hb_match: holdback = float(hb_match.group(1))
    elif "10% withheld" in text: holdback = 10.0
    
    overhead = 0.0
    oh_match = re.search(r'Overhead\s*(\d+)%', text)
    if oh_match: overhead = float(oh_match.group(1))
    elif "25% overhead" in text: overhead = 25.0
    
    budget = []
    site_fees = []
    for m in re.finditer(r'^([A-Za-z0-9+ \-\/]+?)\s+\$([0-9,.]+)', text, re.M):
        name = m.group(1).strip()
        amt = float(m.group(2).replace(',', ''))
        lname = name.lower()
        if lname in ["total due", "amount due", "subtotal", "balance due", "total", "amount", "charge", "fee"]:
            continue
        
        is_site_fee = any(x in lname for x in ["site", "admin", "irb", "start-up", "maintenance"]) or amt > 2500
        if is_site_fee:
            site_fees.append({"name": name, "amount": amt, "cap": None})
        else:
            budget.append({"visit_name": name, "amount": amt})
    
    return {
        "type": "CTA",
        "study_id": study_id,
        "investigator": investigator,
        "site_id": site_id,
        "sponsor": sponsor,
        "holdback_percent": holdback,
        "overhead_percent": overhead,
        "budget": budget,
        "site_fees": site_fees,
        "text": text,
        "_source_file": filename
    }

def parse_invoice(text, filename):
    invoice_id_match = re.search(r'(?:Invoice #|Reference #|Invoice Number|No\.)[\s:]*([A-Z0-9-]+)', text, re.I)
    amount_match = re.search(r'(?:Total Due|Total|Balance Due|Amount Due|Net paid|Amount Paid)[\s:]*\$([0-9,.]+)', text, re.I)
    
    invoice_id = invoice_id_match.group(1) if invoice_id_match else "UNKNOWN"
    amount = float(amount_match.group(1).replace(',', '')) if amount_match else 0.0
    
    study_match = re.search(r'\b([A-Z]{3}-\d{3}-\d{3})\b', text)
    study_id = study_match.group(1) if study_match else "UNKNOWN"
    
    subject_match = re.search(r'\b(S-\d{2}-\d{3})\b', text)
    subject_id = subject_match.group(1) if subject_match else "UNKNOWN"
    
    date_match = re.search(r'(?:Date|Invoice date)[\s:]*(\d{4}-\d{2}-\d{2})', text, re.I)
    date = date_match.group(1) if date_match else "UNKNOWN"
    
    site_match = re.search(r'\b(ARP-\d+)\b', text)
    site_id = site_match.group(1) if site_match else "UNKNOWN"
    
    inv_match = re.search(r'(?:Principal Investigator|PI|Pl|P!|Investigator)[:\-\s]*([A-Za-z ]+)(?:\n|,| - |$)', text)
    investigator = inv_match.group(1).strip() if inv_match else "Unknown"

    line_items = []
    for m in re.finditer(r'^([A-Za-z0-9 \-\/]+?)\s+\$([0-9,.]+)', text, re.M):
        desc = m.group(1).strip()
        amt = float(m.group(2).replace(',', ''))
        lname = desc.lower()
        if lname not in ["total due", "amount due", "subtotal", "balance due", "total", "amount", "charge"]:
            line_items.append({"description": desc, "amount": amt})
    
    return {
        "type": "Invoice",
        "invoice_id": invoice_id,
        "study_id": study_id,
        "site_id": site_id,
        "investigator": investigator,
        "subject_id": subject_id,
        "date": date,
        "total_amount": amount,
        "line_items": line_items,
        "text": text,
        "_source_file": filename
    }

def parse_remittance(text, filename):
    remit_match = re.search(r'\b((?:LR|R|RMP|R-INV|RMP-N)-[A-Z0-9-]+)\b', text, re.I)
    remit_id = remit_match.group(1) if remit_match else "UNKNOWN"
    
    amount_match = re.search(r'(?:Total Payment|Amount|Total|Total remitted|Net paid)[\s:]*\$([0-9,.]+)', text, re.I)
    total_paid = float(amount_match.group(1).replace(',', '')) if amount_match else 0.0
    
    date_match = re.search(r'(?:Date|Payment date|Paid on)[\s:]*(\d{4}-\d{2}-\d{2})', text, re.I)
    date = date_match.group(1) if date_match else "UNKNOWN"
    
    payor_match = re.search(r'(?:Payor|From)[\s:]*([A-Za-z ]+)', text)
    payor = payor_match.group(1).strip() if payor_match else "UNKNOWN"
    
    lines = []
    blocks = text.split("INV-")
    for block in blocks[1:]:
        m_id = re.match(r'^([A-Z0-9-]+)', block)
        if m_id:
            inv_id = "INV-" + m_id.group(1)
            # Find the first few amounts up to the next logical block or "Total"
            sub_block = block.split("Total")[0]
            amts = re.findall(r'\$([0-9,.]+)', sub_block)
            paid = float(amts[-1].replace(',', '')) if amts else 0.0
            lines.append({"invoice_id": inv_id, "amount_paid": paid})
        
    return {
        "type": "Remittance",
        "remittance_id": remit_id,
        "payor": payor,
        "date": date,
        "total_paid": total_paid,
        "lines": lines,
        "text": text,
        "_source_file": filename
    }

def process_file(file_path):
    filename = os.path.basename(file_path)
    cache_path = os.path.join(CACHE_DIR, f"{filename}.json")
    
    if os.path.exists(cache_path):
        return
        
    print(f"Parsing {filename}...")
    if filename.endswith(".pdf"):
        text = extract_text(file_path)
        if "Clinical Trial Agreement" in text or "CTA" in filename:
            data = parse_cta(text, filename)
        elif "Remittance" in text or "Payment Advice" in text or "R-" in filename or "Ledger Run" in text or "RMP" in text:
            data = parse_remittance(text, filename)
        elif "Invoice" in text or "Statement of Charges" in text or "INV" in filename:
            data = parse_invoice(text, filename)
        else:
            data = {"type": "Unknown", "text": text, "_source_file": filename}
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        data = {"type": "Comm", "text": text, "_source_file": filename}
        
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)

def main():
    files = glob.glob(os.path.join(DATA_DIR, "*.pdf")) + glob.glob(os.path.join(DATA_DIR, "*.eml")) + glob.glob(os.path.join(DATA_DIR, "*.md"))
    for f in files:
        process_file(f)
    print("Local parsing done.")

if __name__ == "__main__":
    main()
