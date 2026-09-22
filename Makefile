.PHONY: install api frontend frontend-react test lint bootstrap-causrca prepare-causrca validate-data benchmark-causrca benchmark-fault-onset benchmark-false-positive

install:
	python -m pip install -e '.[dev]'

api:
	uvicorn app.main:app --app-dir backend --reload --port 8000

# Legacy comparison/recovery UI. The Continuum release path is frontend-react.
frontend:
	streamlit run frontend/app.py

frontend-react:
	npm --prefix frontend run build
	npm --prefix frontend start

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

benchmark-fault-onset:
	python -m evals.run_fault_onset_benchmark

benchmark-false-positive:
	python -m evals.run_false_positive_benchmark
