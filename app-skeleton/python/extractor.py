import os
import glob
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv("../../.env")

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
  "study_id": "the protocol ID like ABC-123-456",
  "protocol_name": "short protocol name",
  "effective_date": "YYYY-MM-DD",
  "net_days": 30,
  "site_id": "...",
  "investigator": "...",
  "sponsor": "...",
  "holdback_percent": 0.0,
  "overhead_percent": 0.0,
  "autopayer_system": string(eClinicalGPS)|null,
  "budget": [
     {"visit_name": "Screening", "amount": 1000.00, "is_autopaid": false}
  ],
  "site_fees": [
     {"name": "Start-up", "amount": 5000.00, "cap": null, "cadence": "one-time", "is_autopaid": false}
  ]
}

If Invoice:
{
  "type": "Invoice",
  "invoice_id": "INV-001",
  "payer":"...",
  "study_id": "...",
  "protocol": "...",
  "investigator": "...",
  "invoice_date": "YYYY-MM-DD",
  "service_date": "YYYY-MM-DD",
  "subject_id": "...",
  "total_amount": 1000.00,
  "line_items": [
     {"description": "Screening Visit", "amount": 1000.00}
  ],
  "net": number|null,
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
  "study_id": "ABC-123-456",
  "protocol_name": "short protocol name",
  "site_id": "",
  "subject_id": "A-01-001",
  "visit_name": "screening",
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
  "amount": null,
  "status_update": "paid/unpaid/disputed",
  "study_id": "...",
  "site_id": "..."
}

Respond ONLY with the JSON object. If any field is empty, put in null.Do not include markdown formatting or any other text.
"""

import base64
from io import BytesIO
from pdf2image import convert_from_path

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

    print(f"Processing {filename}")
    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ.get("GROQ_API_KEY")
        )
        
        content_array = [
            {"type": "text", "text": f"Filename: {filename}\n\n{PROMPT_TEMPLATE}"}
        ]

        if file_path.endswith(".pdf"):
            images = convert_from_path(file_path, 300)
            for img in images:
                b64 = encode_image(img)
                content_array.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            content_array[0]["text"] += f"\n\nText:\n{text}"

        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content_array}],
            temperature=0
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
        for future in as_completed(futures):
            results.append(future.result())
            time.sleep(5.5)  

    print("Done extracting.")

if __name__ == "__main__":
    main()
