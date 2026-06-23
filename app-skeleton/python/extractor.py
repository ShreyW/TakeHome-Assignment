import os
import glob
import json
import time
import base64
from io import BytesIO
from pdf2image import convert_from_path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

# Read OpenRouter API key from .env
env_key = None
if os.path.exists("../../.env"):
    with open("../../.env", "r") as f:
        for line in f:
            if line.startswith("OPENROUTER_API_KEY="):
                env_key = line.strip().split("=", 1)[1]

api_key = os.environ.get("OPENROUTER_API_KEY", env_key)
client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=api_key,
)

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
  "status_update": "unpaid/disputed"
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
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Filename: {filename}\n\n" + PROMPT_TEMPLATE}
                ]
            }
        ]

        if filename.endswith(".pdf"):
            pages = convert_from_path(file_path, 150) # lower DPI for faster processing/cheaper
            for page in pages[:3]: # limit to 3 pages to avoid huge prompts
                base64_image = encode_image(page)
                messages[0]["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            messages[0]["content"].append({"type": "text", "text": f"Content:\n{content}"})
            
        completion = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages,
            temperature=0.0
        )
        
        text = completion.choices[0].message.content
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        parsed = json.loads(text.strip())
        parsed["_source_file"] = filename
        
        with open(cache_path, "w") as f:
            json.dump(parsed, f, indent=2)
            
        return parsed
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        return {"_source_file": filename, "error": str(e)}

def main():
    files = []
    for ext in ["*.pdf", "*.eml", "*.md"]:
        files.extend(glob.glob(os.path.join(DATA_DIR, ext)))
        
    print(f"Found {len(files)} files to extract via LLM.")
    
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_file, f): f for f in files}
        for future in as_completed(futures):
            results.append(future.result())
            
    print("Done extracting.")

if __name__ == "__main__":
    main()
