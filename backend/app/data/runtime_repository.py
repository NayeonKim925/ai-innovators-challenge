"""Runtime repository that deliberately cannot read evaluation data."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..domain import DatasetName, Incident

FORBIDDEN_RUNTIME_KEYS = frozenset(
    {
        "label",
        "label_value",
        "root_cause",
        "ground_truth",
        "manipulated_variable",
        "diagnosis_time",
        "fault_name",
        "split",
        # AGENT_FAULT_DETECTION_PLAN.md Phase 1: these causRCA `causes.json` timing
        # fields are captured in `data/evaluation/causrca/cases.json` only, to score
        # the fault-onset detector. They must never reach runtime -- the detector
        # estimates onset from observable alarms alone (analytics/fault_onset.py).
        "cause_start_at",
        "cause_end_at",
    }
)


def runtime_root() -> Path:
    return Path(os.getenv("RUNTIME_DATA_DIR", "data/runtime")).resolve()


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_RUNTIME_KEYS.intersection(value)
        if forbidden:
            raise ValueError(f"Runtime data contains forbidden evaluation keys: {sorted(forbidden)}")
        for nested in value.values():
            _reject_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_keys(nested)


class JsonRuntimeRepository:
    """Reads one prepared incident index per dataset from `data/runtime`.

    Data preparation scripts are responsible for creating these files. This repository
    intentionally has no path or import for `data/evaluation`.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or runtime_root()).resolve()
        self._cache: dict[DatasetName, list[Incident]] = {}

    def _path_for(self, dataset: DatasetName) -> Path:
        path = (self.root / dataset.value / "incidents.json").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Runtime incident path escaped data root")
        return path

    def list_incidents(self, dataset: DatasetName | None = None) -> list[Incident]:
        datasets = [dataset] if dataset else list(DatasetName)
        incidents: list[Incident] = []
        for name in datasets:
            if name in self._cache:
                incidents.extend(self._cache[name])
                continue
            path = self._path_for(name)
            if not path.exists():
                self._cache[name] = []
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError(f"Runtime index must be a list: {path}")
            _reject_forbidden_keys(payload)
            parsed = [Incident.model_validate(item) for item in payload]
            self._cache[name] = parsed
            incidents.extend(parsed)
        return incidents

    def get_incident(self, incident_id: str) -> Incident | None:
        return next((item for item in self.list_incidents() if item.id == incident_id), None)

    def dataset_status(self, dataset: DatasetName) -> dict[str, object]:
        incidents = self.list_incidents(dataset)
        capability_union = sorted({cap.value for item in incidents for cap in item.capabilities})
        return {
            "dataset": dataset.value,
            "status": "ready" if incidents else "unprepared",
            "incident_count": len(incidents),
            "capabilities": capability_union,
        }
