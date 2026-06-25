import json
from pathlib import Path
import csv

clincards = []
for f in Path("app-skeleton/python/cache").glob("ClinCard_*.json"):
    with open(f) as fp:
        clincards.append(json.load(fp))

ctms = []
with open("documents/realtime_visit_log.csv") as f:
    for row in csv.DictReader(f):
        ctms.append(row["SubjectID"])

for c in clincards:
    subj = c.get("subject_id", "")
    if "19-" in subj:
        subj = subj.replace("19-", "12-")
    
    if subj not in ctms:
        print(f"ClinCard subject {subj} NOT in CTMS!")
    else:
        print(f"ClinCard subject {subj} is in CTMS.")
