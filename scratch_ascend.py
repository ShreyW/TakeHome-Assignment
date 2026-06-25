import json

with open("out/study-02-ascend/chains.json") as fp:
    chains = json.load(fp)

invs = chains["invoice_to_payment"]
print("INVOICES:")
for inv in invs:
    print(f"  {inv['invoice_id']}: ${inv['invoice_amount']} -> Settled: ${inv['amount_settled']} (Status: {inv['status']})")

print("\nREMITTANCES/PAYMENTS:")
for pt in chains["payment_to_remittance"]:
    print(f"  Payment {pt['payment_id']}: {pt.get('notes')}")

print("\nAUTOPAYS (from dashboard calculation actually, we need to read eclinicalgps to match)")
