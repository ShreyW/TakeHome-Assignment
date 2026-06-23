// Minimal reconciliation-service skeleton (Go stdlib only).
// Implement reconcile(): ingest DATA_DIR -> model -> write the four files per OUTPUT_CONTRACT.md.
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
)

var studies = []string{"study-01-horizon", "study-02-ascend", "study-03-northstar"}

func outDir() string {
	if v := os.Getenv("OUT_DIR"); v != "" {
		return v
	}
	return "out"
}

func write(path string, v interface{}) {
	b, _ := json.MarshalIndent(v, "", "  ")
	_ = os.WriteFile(path, b, 0644)
}

// reconcile: TODO parse DATA_DIR, model entities, resolve the six chains, compute the products.
func reconcile() map[string]interface{} {
	for _, s := range studies {
		d := filepath.Join(outDir(), s)
		_ = os.MkdirAll(d, 0755)
		write(filepath.Join(d, "chains.json"), map[string]interface{}{
			"study_id": s, "payment_to_remittance": []any{}, "invoice_to_payment": []any{},
			"invoice_to_activities": []any{}, "remittance_to_activities": []any{},
			"activity_to_cta": []any{}, "entity_scope": []any{}})
		write(filepath.Join(d, "dashboard.json"), map[string]interface{}{
			"study_id": s, "total_billed": 0, "total_collected": 0, "outstanding_ar": 0,
			"holdback_withheld": 0, "unbilled_estimate": 0, "exceptions_count": 0,
			"avg_days_to_payment": nil})
		_ = os.WriteFile(filepath.Join(d, "unbilled.json"), []byte("[]"), 0644)
		_ = os.WriteFile(filepath.Join(d, "unpaid.json"), []byte("[]"), 0644)
	}
	return map[string]interface{}{"status": "done", "studies": studies, "out": outDir()}
}

func main() {
	for _, a := range os.Args[1:] {
		if a == "--reconcile" {
			fmt.Println(reconcile())
			return
		}
	}
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})
	http.HandleFunc("/reconcile", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(reconcile())
	})
	// TODO: expose your chains here, e.g. GET /chains/<study>
	fmt.Println("serving on :8080")
	_ = http.ListenAndServe("0.0.0.0:8080", nil)
}
