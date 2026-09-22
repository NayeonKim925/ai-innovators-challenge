"""causRCA normal-operation baseline loader.

Mirrors `metal_etch_adapter.NormalWaferRecord` / `load_normal_baseline`: a
normal-operation recording is not an `Incident` (it is never investigated),
just a runtime artifact `analytics/causrca_anomaly.py` reads to fit a
"what does normal look like" model. `scripts/prepare_causrca.py` is the only
writer of `data/runtime/causrca/normal_baseline.json`; this module only reads
it, so it carries no dependency on the causRCA CSV format itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..domain import Observation


class NormalOperationRecord(BaseModel):
    """One `real_op` recording: a complete normal production cycle, unlabeled."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    observations: list[Observation]


def load_normal_baseline(runtime_root: Path) -> list[NormalOperationRecord]:
    """Read `data/runtime/causrca/normal_baseline.json`, or `[]` if unprepared."""
    path = runtime_root / "causrca" / "normal_baseline.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [NormalOperationRecord.model_validate(item) for item in payload]
