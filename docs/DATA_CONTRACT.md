# Data contract and isolation policy

## Dataset boundary

`source_dataset` is mandatory on every incident. A dataset adapter may normalize its
own source into the shared contract, but may not join entities across sources.

## Storage zones

| Zone | Permitted content | Runtime access |
| --- | --- | --- |
| `data/raw/` | Original downloaded material | Preparation only |
| `data/runtime/` | Case metadata and observations available before investigation cutoff | Yes |
| `data/evaluation/` | Root-cause truth, split assignments, diagnosis labels | No |
| `data/processed/` | Reproducible derived artifacts with manifest | Preparation only unless explicitly exported |

## Runtime incident schema

```json
{
  "id": "case_123",
  "source_dataset": "causrca",
  "title": "Prepared incident",
  "time_range_s": {"start": 0.0, "end": 3600.0},
  "capabilities": ["time_series", "root_cause_ranking"],
  "observations": [
    {"time_s": 12.0, "signal": "P101", "value": "True", "kind": "Alarm"}
  ]
}
```

Forbidden runtime keys include `label`, `label_value`, `root_cause`, `ground_truth`,
`manipulated_variable`, `diagnosis_time`, `fault_name`, and `split`.

## Evidence contract

Every candidate references one or more `Evidence` items. An evidence item must identify
the observed signal, time, deterministic tool, or cited source that supports it.
Candidates without evidence are marked `inconclusive`, not ranked as a likely cause.
