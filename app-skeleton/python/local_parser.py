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
    study_id = "UNKNOWN"
    if "MRD-204-017" in text: study_id = "MRD-204-017"
    elif "VTX-330-201" in text: study_id = "VTX-330-201"
    elif "CLX-115-300" in text: study_id = "CLX-115-300"
    
    holdback = 0.0
    if "Holdback 10%" in text or "10% withheld" in text: holdback = 10.0
    
    overhead = 0.0
    if "Overhead 25%" in text or "25% overhead" in text: overhead = 25.0
    
    return {
        "type": "CTA",
        "study_id": study_id,
        "holdback_percent": holdback,
        "overhead_percent": overhead,
        "text": text,
        "_source_file": filename
    }

def parse_invoice(text, filename):
    invoice_id_match = re.search(r'(?:Invoice #|Reference #|Invoice Number)[\s:]*([A-Z0-9-]+)', text, re.I)
    amount_match = re.search(r'(?:Total Due|Total|Balance Due|Amount Due|Net paid|Amount Paid)[\s:]*\$([0-9,.]+)', text, re.I)
    
    invoice_id = invoice_id_match.group(1) if invoice_id_match else "UNKNOWN"
    amount = float(amount_match.group(1).replace(',', '')) if amount_match else 0.0
    
    study_id = "UNKNOWN"
    if "MRD-204-017" in text or "HORIZON" in text: study_id = "MRD-204-017"
    elif "VTX-330-201" in text or "ASCEND" in text: study_id = "VTX-330-201"
    elif "CLX-115-300" in text or "NORTHSTAR" in text: study_id = "CLX-115-300"
    
    return {
        "type": "Invoice",
        "invoice_id": invoice_id,
        "study_id": study_id,
        "total_amount": amount,
        "text": text,
        "_source_file": filename
    }

def parse_remittance(text, filename):
    remit_match = re.search(r'(?:Remittance|Payment Advice|Ledger Run)[\s:]*([A-Z0-9-]+)?', text, re.I)
    amount_match = re.search(r'(?:Total Payment|Amount|Total)[\s:]*\$([0-9,.]+)', text, re.I)
    
    return {
        "type": "Remittance",
        "total_paid": float(amount_match.group(1).replace(',', '')) if amount_match else 0.0,
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
