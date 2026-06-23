// Minimal reconciliation-service skeleton (Node stdlib only).
// Implement reconcile(): ingest DATA_DIR -> model -> write the four files per OUTPUT_CONTRACT.md.
const http = require("http");
const fs = require("fs");
const path = require("path");

const DATA = process.env.DATA_DIR || "documents"; // the one flat pile of all documents
const OUT = process.env.OUT_DIR || "out";
const STUDIES = ["study-01-horizon", "study-02-ascend", "study-03-northstar"];

function reconcile() {
  // TODO: parse DATA, model entities, resolve the six chains, compute the products.
  for (const s of STUDIES) {
    const d = path.join(OUT, s);
    fs.mkdirSync(d, { recursive: true });
    fs.writeFileSync(path.join(d, "chains.json"), JSON.stringify({
      study_id: s, payment_to_remittance: [], invoice_to_payment: [],
      invoice_to_activities: [], remittance_to_activities: [],
      activity_to_cta: [], entity_scope: [] }, null, 2));
    fs.writeFileSync(path.join(d, "dashboard.json"), JSON.stringify({
      study_id: s, total_billed: 0, total_collected: 0, outstanding_ar: 0,
      holdback_withheld: 0, unbilled_estimate: 0, exceptions_count: 0,
      avg_days_to_payment: null }, null, 2));
    fs.writeFileSync(path.join(d, "unbilled.json"), "[]");
    fs.writeFileSync(path.join(d, "unpaid.json"), "[]");
  }
  return { status: "done", studies: STUDIES, out: OUT };
}

if (process.argv.includes("--reconcile")) {
  console.log(reconcile());
} else {
  http.createServer((req, res) => {
    if (req.url === "/healthz") { res.end("ok"); return; }
    if (req.url.startsWith("/reconcile")) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(reconcile()));
      return;
    }
    // TODO: expose your chains here, e.g. GET /chains/<study>
    res.statusCode = 404;
    res.end(JSON.stringify({ error: "not found" }));
  }).listen(8080, () => console.log("serving on :8080"));
}
