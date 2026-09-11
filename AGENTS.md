# Manufacturing Investigation Workspace

This repository builds a research MVP for **manufacturing incident investigation**.
The product helps operators, process experts, and data analysts review the same
observations, root-cause candidates, and human decisions. It is not an automatic
plant-control system and must never present a candidate as a confirmed physical cause.

## Source of truth

- Product scope: `docs/PRODUCT.md`
- Architecture and boundaries: `docs/ARCHITECTURE.md`
- Data contracts and leakage rules: `docs/DATA_CONTRACT.md`
- Metrics and benchmark rules: `docs/EVALUATION.md`
- Design decisions: `docs/decisions/`

Read the relevant document before changing a boundary it governs.

## Non-negotiable data rules

1. Do not join records from different source datasets as if they came from one plant.
2. `data/runtime/` may contain only information observable at investigation time.
3. Labels, manipulated variables, diagnosis timestamps, and benchmark answers belong
   only in `data/evaluation/`; backend runtime code and LLM prompts must not read them.
4. A model or LLM may summarize tool outputs, but numerical anomaly or ranking results
   must come from a deterministic analysis tool with recorded inputs and version.
5. Every user-facing claim needs an observation or cited source. If evidence is missing,
   return an inconclusive result.

## Working agreement

- Keep adapters dataset-specific and map them to the shared incident contract.
- Keep domain, data, analytics, workflow, and API layers separate.
- Add or update tests for every behavior change.
- Do not commit raw data, generated arrays, secrets, local databases, or caches.
- Do not use AI-generated domain text as an authoritative RAG source.
- Record a material scope or data decision as an ADR.

## Definition of done

Run the relevant tests, formatting/lint checks, and document any known evaluation gap.
For changes that touch runtime data, add a leakage test. For workflow changes, verify
the trace identifies each tool call and that no physical action is proposed.
