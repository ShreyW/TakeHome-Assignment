# Convenience targets. Edit `reconcile` to run YOUR service.
.PHONY: reconcile selfcheck up clean

# Run your service end-to-end over data/ and write out/<study>/{chains,dashboard,unbilled,unpaid}.json.
# The default points at the Python skeleton; replace with your own entry point.
reconcile:
	python3 app-skeleton/python/main.py --reconcile

# Validate your out/ structure and score it against the public sample.
selfcheck:
	python3 conformance/run_conformance.py --out ./out

# Bring up the optional Postgres + your app container.
up:
	docker compose up --build

clean:
	rm -rf out
