# App skeletons

Minimal, runnable starting points in three languages. **Pick one or ignore them entirely** — your
stack is your choice; this just saves you the boilerplate so you can start on the reconciliation.

Each skeleton:
- boots an HTTP server with `GET /healthz` → `ok`,
- exposes `GET /reconcile` (and a `--reconcile` CLI flag) that writes the four canonical answer files
  under `out/<study>/` — currently **empty stubs you must fill in** (see `OUTPUT_CONTRACT.md`),
- has **no parsing/recon dependencies baked in** — that's deliberate. Parse the PDFs however you like
  (any LLM is fine), then model and reconcile.

## Run a skeleton directly

```bash
# python
cd app-skeleton/python && python3 main.py --reconcile      # writes ./out
python3 main.py                                            # serves on :8080

# node
cd app-skeleton/node && node server.js --reconcile

# go
cd app-skeleton/go && go run . --reconcile
```

## Or via docker-compose (from the repo root)

```bash
# edit docker-compose.yml `build:` to your language, then:
docker compose up --build
curl localhost:8080/healthz
curl localhost:8080/reconcile      # writes ./out via the mounted volume
```

A Postgres is available at `db:5432` (user `postgres`, pass `recon`, db `recon`) if you want a
relational store. You are free to design the schema — that's part of what we're evaluating.

## Where to put your logic

In each skeleton, the `reconcile()` function is the single entry point. Implement: ingest `DATA_DIR`
→ model the entities → resolve the six chains → write the four files to `OUT_DIR`. Keep ingestion,
normalization, matching, and serving as separate, testable pieces.
