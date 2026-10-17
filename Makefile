.PHONY: run test lint benchmark

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

test:
	pytest -q

lint:
	ruff check app tests scripts

benchmark:
	python scripts/benchmark.py
