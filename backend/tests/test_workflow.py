import json
from pathlib import Path

import pytest
from app.analytics import metal_etch_pca
from app.data.metal_etch_adapter import build_metal_etch_dataset
from app.domain import Candidate, Capability, DatasetName, Incident, Observation, TimeRange
from app.workflows.investigation import investigate


def incident() -> Incident:
    return Incident(
        id="case_1",
        source_dataset=DatasetName.CAUSRCA,
        title="Prepared incident",
        time_range_s=TimeRange(start=0, end=10),
        capabilities={Capability.TIME_SERIES, Capability.ROOT_CAUSE_RANKING},
        observations=[
            Observation(time_s=2, signal="P101", value=True, kind="Alarm"),
            Observation(time_s=5, signal="T201", value=True, kind="Alarm"),
            Observation(time_s=8, signal="P101", value=False, kind="Alarm"),
            Observation(time_s=9, signal="T201", value=False, kind="Alarm"),
        ],
    )


def test_workflow_only_ranks_alarms_active_at_cutoff() -> None:
    result = investigate(incident(), diagnosis_time=6)

    assert [candidate.signal for candidate in result.candidates] == ["T201", "P101"]
    assert len(result.evidence) == 2
    assert [event.tool for event in result.trace] == [
        "validate_request",
        "active_alarm_recency_baseline",
        "evidence_check",
        "prepare_human_review",
    ]


def test_workflow_abstains_without_active_alarm() -> None:
    result = investigate(incident(), diagnosis_time=9)

    assert result.candidates == []
    assert any("abstains" in warning for warning in result.warnings)


def test_evidence_check_demotes_candidates_with_unresolvable_evidence() -> None:
    """ADR-0002 / IMPLEMENTATION_PLAN.md M4: evidence_check must actually demote
    a candidate whose evidence_ids do not resolve against the returned evidence
    list, rather than just documenting the rule in prose."""
    from app.domain import TraceEvent
    from app.workflows.investigation import evidence_check

    state = {
        "candidates": [
            Candidate(
                rank=1,
                signal="P101",
                reason="looks suspicious",
                evidence_ids=["E_missing"],
            )
        ],
        "evidence": [],  # no Evidence object exists for "E_missing"
        "warnings": [],
        "trace": [TraceEvent(step=1, tool="validate_request", detail="ok")],
    }

    result = evidence_check(state)

    assert result["candidates"][0].status == "inconclusive"
    assert any("demoted" in warning for warning in result["warnings"])
    assert result["trace"][-1].tool == "evidence_check"


@pytest.fixture(autouse=True)
def _clear_metal_etch_model_cache():
    """ADR-0002: METAL_ETCH 워크플로우 테스트가 이전 테스트의 PCA 기준선
    캐시를 재사용하지 않도록 매 테스트 전후로 비운다."""
    metal_etch_pca._MODEL_CACHE.clear()
    yield
    metal_etch_pca._MODEL_CACHE.clear()


@pytest.mark.filterwarnings(
    "ignore:Mean of empty slice:RuntimeWarning",
    "ignore:Degrees of freedom <= 0 for slice:RuntimeWarning",
    "ignore:All-NaN slice encountered:RuntimeWarning",
    "ignore:Skipping features without any observed values:UserWarning",
    "ignore:invalid value encountered in divide:RuntimeWarning",
)
def test_workflow_uses_metal_etch_pca_tool_for_metal_etch_incidents(
    tmp_path: Path, synthetic_machine_mat: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0002: METAL_ETCH source_dataset은 causRCA/recency 폴백이 아니라
    metal_etch_pca_contribution 도구로 분석돼야 한다 (investigation.py의
    대칭 분기 회귀 테스트)."""
    dataset = build_metal_etch_dataset(synthetic_machine_mat)
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))
    metal_etch_dir = runtime_dir / "metal_etch"
    metal_etch_dir.mkdir(parents=True)
    baseline_payload = [item.model_dump(mode="json") for item in dataset.normal_baseline]
    (metal_etch_dir / "normal_baseline.json").write_text(
        json.dumps(baseline_payload), encoding="utf-8"
    )

    metal_etch_incident = dataset.incidents[0]
    result = investigate(metal_etch_incident, diagnosis_time=metal_etch_incident.time_range_s.end)

    assert result.dataset is DatasetName.METAL_ETCH
    assert "metal_etch_pca_contribution" in [event.tool for event in result.trace]
    assert all(candidate.evidence_ids for candidate in result.candidates)


def test_workflow_metal_etch_abstains_without_prepared_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "empty_runtime"))
    metal_etch_incident = Incident(
        id="metal_etch_9999",
        source_dataset=DatasetName.METAL_ETCH,
        title="No baseline available",
        time_range_s=TimeRange(start=0, end=1),
        capabilities={Capability.TIME_SERIES},
        observations=[Observation(time_s=0, signal="BCl3 Flow", value=1.0, kind="Measurement")],
    )

    result = investigate(metal_etch_incident, diagnosis_time=1)

    assert result.candidates == []
    assert any("prepare_metal_etch" in warning for warning in result.warnings)
