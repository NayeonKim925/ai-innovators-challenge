# Manufacturing Incident Investigation

Evidence-first research MVP for investigating manufacturing anomalies. The service is
designed for an operator, process expert, and data analyst to inspect the same
observations, candidate causes, and review history.

It is not a plant-control system. A ranked signal is an investigation candidate, not a
confirmed physical root cause or maintenance instruction.

## Current build status

- Shared runtime incident, evidence, candidate, and trace contracts: implemented
- Data leakage guard between runtime observations and evaluation truth: implemented
- FastAPI contract and bounded LangGraph workflow: implemented
- Transparent active-alarm recency baseline: implemented
- causRCA preparation and benchmark integration: next milestone
- Metal Etch portability adapter: next milestone
- Review persistence and React investigation UI: next milestone

## Product and data decisions

The MVP has one workflow: **investigate a manufacturing anomaly collaboratively**.

- causRCA is the primary benchmark because it has usable root-cause evaluation truth.
- Metal Etch is a separate semiconductor portability adapter; it is not pooled with
  causRCA and is not used for the headline ranking metric.
- PHM, SECOM, and WM-811K are explicitly deferred rather than partially implemented.

Read [product scope](docs/PRODUCT.md), [data contract](docs/DATA_CONTRACT.md), and
[evaluation plan](docs/EVALUATION.md) before adding a dataset or model.

## Local setup

Python 3.10 or later is required.

```sh
python -m pip install -e '.[dev]'
make test
make lint
make api
```

The API starts at `http://127.0.0.1:8000`; OpenAPI documentation is at `/docs`.
Without a prepared runtime bundle, `/api/datasets` reports `unprepared` and the service
does not fabricate demo incidents.

## Repository map

```text
backend/app/domain.py      Shared, runtime-safe data contracts
backend/app/data/          Dataset adapters and runtime-only repository
backend/app/analytics/     Deterministic analysis tools
backend/app/workflows/     Bounded LangGraph orchestration
backend/tests/             API, workflow, and data-leakage tests
data/                      Ignored raw/runtime/evaluation zones
docs/                      Product, architecture, evaluation, ADRs
scripts/                   Reproducible preparation commands
```

## Data safety

Evaluation labels never enter `data/runtime/`. The runtime repository rejects common
truth fields such as `root_cause`, `label_value`, and `diagnosis_time`, and tests enforce
this rule. New raw data, generated artifacts, local databases, and secrets are ignored
by Git. Previously tracked Metal Etch assets are a legacy migration item and must not be
extended; they will be untracked only after a reproducible download script is in place.

## Legacy exploration files

The top-level Metal Etch loaders and `processed/` outputs predate this architecture.
They are retained temporarily as research material and will be migrated to a dedicated
Metal Etch adapter. Do not extend their metadata format as a service API.
