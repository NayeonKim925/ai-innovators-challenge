# Development guide

## One workflow, two dataset roles

The MVP is a collaborative **manufacturing anomaly investigation** service, not a
collection of unrelated ML demos.

| Dataset | Role | Claim we can make |
| --- | --- | --- |
| causRCA | Primary benchmark | Measurable root-cause ranking on held-out HIL incidents |
| Metal Etch | Portability adapter | Same incident/evidence workflow can represent multi-source semiconductor signals |
| PHM / SECOM / WM-811K | Deferred | Future adapter candidates only |

Never pool these datasets or imply that their entities belong to the same factory.

## Implementation order

1. Prepare causRCA into isolated `runtime` and `evaluation` zones.
2. Integrate the official deterministic RCA tool and establish reproducible metrics.
3. Add evidence assembly and human-review persistence.
4. Implement the investigation UI around incident, evidence, candidate, and review.
5. Migrate Metal Etch preprocessing into a dedicated adapter and demonstrate portability.
6. Add optional LLM explanation only after deterministic analysis and evidence checks pass.

## Dataset adapter contract

Every adapter emits a source-specific record first, then maps it into the shared
runtime incident contract. Capabilities are declared explicitly: for example, a dataset
may support time series and multi-source evidence but not a valid causal-graph metric.

Evaluation labels never enter the runtime incident model. See
[data contract](docs/DATA_CONTRACT.md) for prohibited fields and
[architecture](docs/ARCHITECTURE.md) for package boundaries.

## Legacy Metal Etch work

The root loaders, `preprocess.py`, and `processed/` artifacts were early data
exploration. They remain useful for understanding the public LAM 9600 data, but are not
the service API. Before reuse, migrate them to `backend/app/data/metal_etch_adapter.py`,
split observable data from labels, and validate the preprocessing assumptions.
