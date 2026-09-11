.PHONY: install api test lint

install:
	python -m pip install -e '.[dev]'

api:
	uvicorn app.main:app --app-dir backend --reload --port 8000

test:
	python -m pytest -q

lint:
	python -m ruff check .
