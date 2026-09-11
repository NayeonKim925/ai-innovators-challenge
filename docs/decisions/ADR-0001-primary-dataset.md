# ADR-0001: Use causRCA as the primary benchmark

## Decision

Use causRCA for the MVP's primary root-cause ranking evaluation. Keep Metal Etch as a
separate portability adapter and semiconductor demonstration dataset.

## Why

causRCA provides explicit evaluation truth suitable for ranking metrics. Metal Etch is
valuable for its multi-source process observations, but its public fault names do not
provide sufficiently precise variable-level truth for the headline benchmark.

## Consequence

The service shares one incident/evidence contract across adapters, while analytics and
metrics remain dataset-capability-specific. No results are pooled across datasets.
