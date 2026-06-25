import json
from pathlib import Path

cache_dir = Path("app-skeleton/python/cache")
for f in cache_dir.glob("R-*.json"):
    with open(f, "r") as fp:
        data = json.load(fp)
        if data.get("type") == "Remittance":
            print(f"\n{f.name}:")
            for line in data.get("lines", []):
                print(f"  {line}")
