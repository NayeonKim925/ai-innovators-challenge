.PHONY: install api frontend test lint bootstrap-causrca prepare-causrca validate-data benchmark-causrca

install:
	python -m pip install -e '.[dev]'

api:
	uvicorn app.main:app --app-dir backend --reload --port 8000

frontend:
	streamlit run frontend/app.py

test:
	python -m pytest -q

lint:
	python -m ruff check .

bootstrap-causrca:
	python scripts/bootstrap_causrca.py

prepare-causrca:
	python scripts/prepare_causrca.py --source data/raw/causrca

validate-data:
	python scripts/validate_data.py

benchmark-causrca:
	python -m evals.run_causrca_benchmark --method time_recency
