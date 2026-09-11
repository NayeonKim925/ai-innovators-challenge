# Product scope

## Problem

When a manufacturing anomaly occurs, an operator, process expert, and data analyst
often inspect separate dashboards and files. The team needs a shared, auditable way to
move from observed signals to a **reviewable investigation**, rather than an AI answer
with no traceable basis.

## MVP

The MVP accepts a prepared incident, runs deterministic anomaly/root-cause tools,
collects observation-linked evidence, drafts a bounded investigation report, and stores
an explicit human decision. It does not control equipment, issue repair instructions,
or claim a diagnosed candidate is a confirmed cause.

## Dataset strategy

- **Primary benchmark:** causRCA. It supplies HIL incidents and evaluation truth for
  measurable root-cause ranking.
- **Portability adapter:** Metal Etch. It demonstrates that the same incident/evidence
  workflow can represent a different semiconductor data structure. Its weak fault-label
  mapping must not be used for the primary performance claim.
- PHM, SECOM, and WM-811K are future adapters, not MVP features.

## Users

| Role | Primary need |
| --- | --- |
| Operator | See the incident and provide observed context. |
| Process or equipment expert | Examine evidence and approve, reject, or correct a candidate. |
| Data analyst | Inspect tool inputs, data quality, and benchmark results. |
| Manager | Track investigation status and decision history. |

## Non-goals

- A generic upload-any-data AI platform
- Autonomous repair, control, or maintenance instructions
- Cross-dataset causal claims
- Training an LLM on private manufacturing data
