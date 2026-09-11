# Evaluation plan

## Primary benchmark: causRCA

The service is evaluated on held-out causRCA fault cases. Runtime code receives only
observations up to the chosen diagnosis cutoff. Evaluation scripts, and only those
scripts, may read the corresponding root-cause truth.

## Metrics

- Root-cause ranking: Hit@1, Hit@3, MRR, MAP@3
- Workflow: tool-selection success, structured-output validity, trace completeness
- Evidence: unsupported-claim rate, citation/observation alignment, abstention quality
- Product: time to a reviewable report, reviewer agreement, review completion rate

## Required comparisons

1. Deterministic analysis only
2. Deterministic analysis with evidence assembly
3. Full workflow with optional LLM explanation

The LLM must not change numerical scores or access evaluation labels. A comparison that
cannot be reproduced from the supplied data and code must not appear in a presentation.
