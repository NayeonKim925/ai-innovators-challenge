"""Tests for the Metal Etch PCA analytics module (ADR-0002).

`rank_with_pca_contribution` reads its normal-wafer baseline through
`RUNTIME_DATA_DIR` (see `runtime_repository.runtime_root`). Each test sets that
environment variable to its own `tmp_path` so tests do not interfere with each
other's module-level `_MODEL_CACHE` entry.

`synthetic_machine_mat` only carries 3 of the 21 real signals (see `conftest.py`),
so the other 18 columns are entirely NaN for the PCA baseline. numpy/sklearn warn
about that honestly (empty-slice mean, zero-degrees-of-freedom variance); those
warnings are expected here and are not silenced elsewhere in the codebase.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.analytics import metal_etch_pca
from app.data.metal_etch_adapter import build_metal_etch_dataset
from app.domain import Incident

pytestmark = pytest.mark.filterwarnings(
    "ignore:Mean of empty slice:RuntimeWarning",
    "ignore:Degrees of freedom <= 0 for slice:RuntimeWarning",
    "ignore:All-NaN slice encountered:RuntimeWarning",
    "ignore:Skipping features without any observed values:UserWarning",
    "ignore:invalid value encountered in divide:RuntimeWarning",
)


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """`_get_baseline_model`이 `runtime_root()`별로 캐시하므로, 각 테스트가
    자기 `tmp_path`를 새로 쓰더라도 이전 테스트의 캐시 항목이 섞이지 않게
    매 테스트 전후로 캐시를 비운다."""
    metal_etch_pca._MODEL_CACHE.clear()
    yield
    metal_etch_pca._MODEL_CACHE.clear()


def _prepare_runtime(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Incident]:
    """합성 .mat을 어댑터로 변환해 `tmp_path/runtime/metal_etch/`에 쓰고,
    `RUNTIME_DATA_DIR`을 그 경로로 지정한다. entity_id -> Incident 매핑을 반환."""
    dataset = build_metal_etch_dataset(synthetic_machine_mat)
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))

    metal_etch_dir = runtime_dir / "metal_etch"
    metal_etch_dir.mkdir(parents=True)
    (metal_etch_dir / "normal_baseline.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in dataset.normal_baseline]),
        encoding="utf-8",
    )
    return {incident.id: incident for incident in dataset.incidents}


def test_returns_candidates_with_evidence_when_baseline_is_prepared(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incidents = _prepare_runtime(tmp_path, synthetic_machine_mat, monkeypatch)
    incident = incidents["metal_etch_2915"]

    candidates, evidence, warnings = metal_etch_pca.rank_with_pca_contribution(
        incident, diagnosis_time=incident.time_range_s.end
    )

    assert warnings == []
    assert candidates, (
        "expected at least one candidate when the baseline and observations are both present"
    )
    assert len(evidence) == len(candidates)
    for candidate in candidates:
        assert candidate.evidence_ids, (
            "Candidate.evidence_ids must be non-empty (schema requires min_length=1)"
        )
        assert all(eid in {item.id for item in evidence} for eid in candidate.evidence_ids)


def test_respects_limit_parameter(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incidents = _prepare_runtime(tmp_path, synthetic_machine_mat, monkeypatch)
    incident = incidents["metal_etch_2915"]

    candidates, _evidence, _warnings = metal_etch_pca.rank_with_pca_contribution(
        incident, diagnosis_time=incident.time_range_s.end, limit=1
    )

    assert len(candidates) <= 1


def test_abstains_when_baseline_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "empty_runtime"))
    incident = Incident(
        id="metal_etch_9999",
        source_dataset="metal_etch",
        title="No baseline available",
        time_range_s={"start": 0, "end": 1},
        capabilities=set(),
        observations=[{"time_s": 0, "signal": "BCl3 Flow", "value": 1.0, "kind": "Measurement"}],
    )

    candidates, evidence, warnings = metal_etch_pca.rank_with_pca_contribution(
        incident, diagnosis_time=1
    )

    assert candidates == []
    assert evidence == []
    assert warnings and "prepare_metal_etch" in warnings[0]


def test_abstains_when_no_observations_precede_the_cutoff(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incidents = _prepare_runtime(tmp_path, synthetic_machine_mat, monkeypatch)
    incident = incidents["metal_etch_2915"]

    candidates, evidence, warnings = metal_etch_pca.rank_with_pca_contribution(
        incident, diagnosis_time=-1
    )

    assert candidates == []
    assert evidence == []
    assert warnings and "abstains" in warnings[0]


def test_never_returns_the_diagnosis_cutoff_index_as_a_signal(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step Number는 원인 후보가 될 수 없는 인덱스성 신호라 후보에 나오면 안 된다."""
    incidents = _prepare_runtime(tmp_path, synthetic_machine_mat, monkeypatch)
    incident = incidents["metal_etch_2915"]

    candidates, _evidence, _warnings = metal_etch_pca.rank_with_pca_contribution(
        incident, diagnosis_time=incident.time_range_s.end
    )

    assert all(candidate.signal != "Step Number" for candidate in candidates)
    assert all(candidate.signal != "Time" for candidate in candidates)
