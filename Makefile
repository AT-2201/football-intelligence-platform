.PHONY: install db api ingest transform validate test lint

install:
	python -m pip install -e '.[dev]'

db:
	docker compose up -d postgres

api:
	uvicorn football_intelligence.main:app --reload

ingest:
	football ingest

transform:
	football transform

validate:
	football validate

test:
	pytest

lint:
	ruff check .
