import os
import glob
import json
import time
import base64
from io import BytesIO
from pdf2image import convert_from_path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv


DATA_DIR = "../../documents"
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

PROMPT_TEMPLATE = """
You are an expert clinical trial billing reconciliation assistant.
Extract structured information from the provided document.
Return ONLY valid JSON.

Determine the document type and extract relevant fields.

If CTA (Clinical Trial Agreement):
{
  "type": "CTA",
  "study_id": "MRD-204-017 or VTX-330-201 or CLX-115-300",
  "site_id": "...",
  "investigator": "...",
  "sponsor": "...",
  "holdback_percent": 10.0,
  "overhead_percent": 25.0,
  "budget": [
     {"visit_name": "Screening", "procedures": ["Blood Draw", "ECG"], "amount": 2000.00}
  ],
  "site_fees": [
     {"name": "Start-up", "amount": 5000.00, "cap": null}
  ]
}

If Invoice:
{
  "type": "Invoice",
  "invoice_id": "INV-001",
  "study_id": "...",
  "site_id": "...",
  "investigator": "...",
  "date": "YYYY-MM-DD",
  "total_amount": 1000.00,
  "line_items": [
     {"description": "Screening S-12-001", "amount": 1000.00}
  ]
}

If Remittance:
{
  "type": "Remittance",
  "remittance_id": "R-001",
  "payor": "...",
  "date": "YYYY-MM-DD",
  "total_paid": 5000.00,
  "lines": [
     {"invoice_id": "INV-001", "amount_paid": 1000.00}
  ]
}

If ClinCard:
{
  "type": "ClinCard",
  "subject_id": "S-12-037",
  "date": "YYYY-MM-DD",
  "amount": 50.00,
  "description": "..."
}

If Comms (Email/Slack):
{
  "type": "Comm",
  "date": "YYYY-MM-DD",
  "content_summary": "...",
  "mentions_invoices": ["INV-001"],
  "status_update": "unpaid/disputed",
  "study_id": "...",
  "site_id": "..."
}

Respond ONLY with the JSON object. Do not include markdown formatting or any other text.
"""

def encode_image(image):
    buffered = BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def process_file(file_path):
    filename = os.path.basename(file_path)
    cache_path = os.path.join(CACHE_DIR, f"{filename}.json")
    
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f)

    print(f"Processing {filename}...")
    try:

        load_dotenv("../../.env")
        
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ.get("GROQ_API_KEY")
        )

        from local_parser import extract_text
        if file_path.endswith(".pdf"):
            text = extract_text(file_path)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": f"Filename: {filename}\n\nText:\n{text}\n\n{PROMPT_TEMPLATE}"
                }
            ]
        )
        
        content = completion.choices[0].message.content
        data = json.loads(content)
        data["_source_file"] = filename
        
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        return data
        
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        return {"_source_file": filename, "error": str(e)}

def main():
    files = []
    for ext in ["*.pdf", "*.eml", "*.md"]:
        files.extend(glob.glob(os.path.join(DATA_DIR, ext)))
        
    print(f"Found {len(files)} files to extract via LLM.")
    
    results = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(process_file, f): f for f in files}
        import time
        for future in as_completed(futures):
            results.append(future.result())
            time.sleep(5.5)  # Stay under 12k TPM Groq limit
            
    print("Done extracting.")

if __name__ == "__main__":
    main()
