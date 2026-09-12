"""Tests for the Metal Etch adapter (ADR-0002).

These tests use `synthetic_machine_mat` (see `conftest.py`) instead of the real
`MACHINE_Data.mat`, which is not committed to Git and would make these tests fail on
any machine that has not downloaded the dataset locally.
"""

from __future__ import annotations

from pathlib import Path

from app.data.metal_etch_adapter import (
    MetalEtchEvaluationLabel,
    NormalWaferRecord,
    build_metal_etch_dataset,
    load_normal_baseline,
)
from app.data.runtime_repository import _reject_forbidden_keys
from app.domain import DatasetName, Incident


def test_boundary_duplicate_row_is_dropped(synthetic_machine_mat: Path) -> None:
    # 픽스처의 calib_2901은 원본 3행이고 마지막 행이 calib_2902의 첫 행과
    # 동일하다 (경계 중복행). 실측 규칙대로 제거되면 각 웨이퍼는 2개
    # 시점(row_index 0, 1)만 가져야 한다.
    dataset = build_metal_etch_dataset(synthetic_machine_mat)
    wafer_2901 = next(item for item in dataset.normal_baseline if item.entity_id == "2901")
    times = sorted({observation.time_s for observation in wafer_2901.observations})
    assert times == [0.0, 1.0]


def test_faulty_wafers_become_incidents_with_correct_dataset_tag(
    synthetic_machine_mat: Path,
) -> None:
    dataset = build_metal_etch_dataset(synthetic_machine_mat)

    assert {item.id for item in dataset.incidents} == {"metal_etch_2915", "metal_etch_2916"}
    assert all(item.source_dataset is DatasetName.METAL_ETCH for item in dataset.incidents)


def test_normal_wafers_are_not_incidents(synthetic_machine_mat: Path) -> None:
    dataset = build_metal_etch_dataset(synthetic_machine_mat)

    assert len(dataset.normal_baseline) == 2
    assert all(isinstance(item, NormalWaferRecord) for item in dataset.normal_baseline)
    incident_ids = {item.id for item in dataset.incidents}
    assert "metal_etch_2901" not in incident_ids
    assert "metal_etch_2902" not in incident_ids


def test_evaluation_labels_are_never_embedded_in_incidents(synthetic_machine_mat: Path) -> None:
    """★ Data leakage 회귀 테스트 ★ Incident에는 label_value가 절대 없어야 한다."""
    dataset = build_metal_etch_dataset(synthetic_machine_mat)

    for incident in dataset.incidents:
        dumped = incident.model_dump(mode="json")
        assert "label_value" not in dumped
        assert "fault_name" not in dumped
        assert "TCP +50" not in str(dumped)
        assert "RF -12" not in str(dumped)


def test_evaluation_labels_carry_the_fault_information(synthetic_machine_mat: Path) -> None:
    dataset = build_metal_etch_dataset(synthetic_machine_mat)

    by_case = {item.case_id: item for item in dataset.evaluation_labels}
    assert by_case["metal_etch_2915"].label_value == "TCP +50"
    assert by_case["metal_etch_2916"].label_value == "RF -12"
    assert all(isinstance(item, MetalEtchEvaluationLabel) for item in dataset.evaluation_labels)


def test_runtime_repository_forbidden_key_check_accepts_incident_payload(
    synthetic_machine_mat: Path,
) -> None:
    """어댑터가 만든 incidents.json 후보 payload가 `JsonRuntimeRepository`의
    금지 필드 검사를 실제로 통과하는지 확인한다 (data leakage 방어의 이중 검증)."""
    dataset = build_metal_etch_dataset(synthetic_machine_mat)
    payload = [incident.model_dump(mode="json") for incident in dataset.incidents]

    _reject_forbidden_keys(payload)  # raises ValueError if a forbidden key sneaks in


def test_incident_round_trips_through_model_validate(synthetic_machine_mat: Path) -> None:
    dataset = build_metal_etch_dataset(synthetic_machine_mat)

    for incident in dataset.incidents:
        restored = Incident.model_validate(incident.model_dump(mode="json"))
        assert restored.id == incident.id
        assert restored.observations == incident.observations


def test_entity_ids_filter_restricts_output(synthetic_machine_mat: Path) -> None:
    dataset = build_metal_etch_dataset(synthetic_machine_mat, entity_ids=frozenset({"2915"}))

    assert [item.id for item in dataset.incidents] == ["metal_etch_2915"]
    assert dataset.normal_baseline == []


def test_load_normal_baseline_reads_prepared_runtime_json(
    tmp_path: Path, synthetic_machine_mat: Path
) -> None:
    import json

    dataset = build_metal_etch_dataset(synthetic_machine_mat)
    runtime_dir = tmp_path / "runtime" / "metal_etch"
    runtime_dir.mkdir(parents=True)
    payload = [item.model_dump(mode="json") for item in dataset.normal_baseline]
    (runtime_dir / "normal_baseline.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_normal_baseline(tmp_path / "runtime")

    assert len(loaded) == len(dataset.normal_baseline)
    assert {item.entity_id for item in loaded} == {"2901", "2902"}


def test_load_normal_baseline_returns_empty_when_not_prepared(tmp_path: Path) -> None:
    assert load_normal_baseline(tmp_path / "nonexistent") == []
