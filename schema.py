"""Legacy-adapter contracts for offline data preparation.

Runtime code uses `backend.app.domain`. These dataclasses remain at the repository root
for dataset preparation scripts and make the runtime/evaluation boundary explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Modality = Literal["tabular_timeseries", "feature_vector", "image"]
SourceDataset = Literal["causrca", "metal_etch", "phm2018", "secom", "wm811k"]


@dataclass(frozen=True)
class RuntimeRecord:
    """Data observable before an investigation decision.

    Labels and benchmark answers are intentionally absent. Do not add them here.
    """

    source_dataset: SourceDataset
    modality: Modality
    entity_id: str
    process_stage: str
    features: Any
    equipment_id: str | None = None
    timestamp: str | None = None
    raw_ref: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class EvaluationRecord:
    """Offline-only benchmark answer associated with a runtime entity."""

    source_dataset: SourceDataset
    entity_id: str
    label_type: str
    label_value: Any


RUNTIME_META_COLUMNS = [
    "source_dataset",
    "modality",
    "equipment_id",
    "entity_id",
    "process_stage",
    "timestamp",
]

EVALUATION_META_COLUMNS = ["source_dataset", "entity_id", "label_type", "label_value"]
