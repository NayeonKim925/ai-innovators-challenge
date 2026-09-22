from pathlib import Path

import pytest
from app.data.runtime_repository import JsonRuntimeRepository
from app.domain import DatasetName


def test_runtime_rejects_evaluation_truth(tmp_path: Path) -> None:
    path = tmp_path / "causrca"
    path.mkdir()
    (path / "incidents.json").write_text(
        '[{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},"root_cause":"P101","observations":[]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden evaluation keys"):
        JsonRuntimeRepository(tmp_path).list_incidents(DatasetName.CAUSRCA)


def test_runtime_rejects_fault_onset_evaluation_timing(tmp_path: Path) -> None:
    """AGENT_FAULT_DETECTION_PLAN.md Phase 1: `cause_start_at`/`cause_end_at` are
    evaluation-only ground truth for scoring the fault-onset detector; they must
    never leak into a runtime incident (analytics/fault_onset.py only reads
    observable alarms, never this field)."""
    path = tmp_path / "causrca"
    path.mkdir()
    (path / "incidents.json").write_text(
        '[{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},"cause_start_at":2.5,"observations":[]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden evaluation keys"):
        JsonRuntimeRepository(tmp_path).list_incidents(DatasetName.CAUSRCA)


def test_runtime_accepts_observable_incident(tmp_path: Path) -> None:
    path = tmp_path / "causrca"
    path.mkdir()
    (path / "incidents.json").write_text(
        '[{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},"capabilities":["time_series"],'
        '"observations":[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]}]',
        encoding="utf-8",
    )

    incidents = JsonRuntimeRepository(tmp_path).list_incidents(DatasetName.CAUSRCA)

    assert incidents[0].id == "case_1"
    assert incidents[0].observations[0].signal == "P101"
