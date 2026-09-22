import json
from pathlib import Path

import pytest
from app.analytics import causrca_anomaly
from app.domain import Capability, DatasetName, Incident, Observation, TimeRange


@pytest.fixture(autouse=True)
def _clear_causrca_anomaly_model_cache():
    causrca_anomaly._MODEL_CACHE.clear()
    yield
    causrca_anomaly._MODEL_CACHE.clear()


def _write_normal_baseline(runtime_dir: Path, recordings: list[dict]) -> None:
    causrca_dir = runtime_dir / "causrca"
    causrca_dir.mkdir(parents=True, exist_ok=True)
    (causrca_dir / "normal_baseline.json").write_text(json.dumps(recordings), encoding="utf-8")


def _normal_recording(recording_id: str, flow: float) -> dict:
    """A normal-operation recording where Pressure always tracks Flow
    (Pressure = 2 * Flow, plus tiny jitter). PCA-reconstruction anomaly
    detection catches BROKEN CORRELATIONS, not just extreme univariate
    values: with only one truly variant signal, a single principal component
    spans it entirely and reconstructs any point along that same axis with
    zero error regardless of magnitude -- a wildly large-but-still-correlated
    value would not look anomalous. Two correlated signals let a value that
    breaks the correlation (Flow normal, Pressure decoupled) show up as
    reconstruction error, the way it would for a real multivariate baseline.
    Uses `kind="Event"` because that is what `scripts/prepare_causrca.py`
    actually produces for non-Alarm nodes (see causrca_anomaly.py's docstring)."""
    return {
        "recording_id": recording_id,
        "observations": [
            {"time_s": 10.0, "signal": "Flow", "value": str(flow), "kind": "Event"},
            {"time_s": 10.0, "signal": "Pressure", "value": str(2 * flow), "kind": "Event"},
        ],
    }


def _incident(flow_value: float, pressure_value: float) -> Incident:
    return Incident(
        id="case_1",
        source_dataset=DatasetName.CAUSRCA,
        title="Prepared incident",
        time_range_s=TimeRange(start=0, end=10),
        capabilities={Capability.TIME_SERIES},
        observations=[
            Observation(time_s=0, signal="Flow", value=str(flow_value), kind="Event"),
            Observation(time_s=0, signal="Pressure", value=str(pressure_value), kind="Event"),
        ],
    )


def test_compute_anomaly_score_unavailable_without_a_prepared_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "empty_runtime"))

    score, threshold, evidence, warnings = causrca_anomaly.compute_anomaly_score(
        _incident(100.0, 200.0), up_to_time_s=10
    )

    assert score is None
    assert threshold is None
    assert evidence is None
    assert any("baseline is unavailable" in warning for warning in warnings)


def _recording_with_counter(recording_id: str, flow: float, cutting_time: float) -> dict:
    """Like `_normal_recording`, but also carries a cumulative counter
    (`Prog_CuttingTime`-style: only ever increases within one recording, and
    its absolute value differs a lot recording to recording) that must be
    excluded from the PCA feature space rather than dominate the score."""
    record = _normal_recording(recording_id, flow)
    record["observations"] += [
        {"time_s": 0.0, "signal": "CuttingTime", "value": str(cutting_time), "kind": "Event"},
        {"time_s": 5.0, "signal": "CuttingTime", "value": str(cutting_time + 1), "kind": "Event"},
        {"time_s": 10.0, "signal": "CuttingTime", "value": str(cutting_time + 2), "kind": "Event"},
    ]
    return record


def test_compute_anomaly_score_excludes_cumulative_counters_from_the_feature_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))
    # Every normal recording has a wildly different CuttingTime baseline (like
    # real machine session history would), which would dominate SPE if kept.
    normal = [
        _recording_with_counter(f"rec_{i}", flow=100.0 + (i - 5) * 0.05, cutting_time=i * 50_000)
        for i in range(10)
    ]
    _write_normal_baseline(runtime_dir, normal)

    from app.analytics.causrca_anomaly import _get_baseline_model

    model = _get_baseline_model()

    assert model is not None
    assert "CuttingTime" not in model.feature_names
    assert "Flow" in model.feature_names
    assert "Pressure" in model.feature_names


def test_compute_anomaly_score_flags_a_value_far_outside_the_normal_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))
    # Small jitter around 100.0, e.g. 99.85, 99.9, ..., 100.15 -- realistic
    # normal-operation variability, not an unrealistic exact-constant baseline.
    normal = [_normal_recording(f"rec_{i}", flow=100.0 + (i - 5) * 0.05) for i in range(10)]
    _write_normal_baseline(runtime_dir, normal)

    # Correlation-consistent: Pressure = 2 * Flow, exactly like the baseline.
    quiet_score, threshold, quiet_evidence, warnings = causrca_anomaly.compute_anomaly_score(
        _incident(100.0, 200.0), up_to_time_s=10
    )
    # Correlation-BROKEN: Flow is a normal value, but Pressure does not track it.
    deviant_score, _threshold2, deviant_evidence, _warnings2 = (
        causrca_anomaly.compute_anomaly_score(_incident(100.0, 9000.0), up_to_time_s=10)
    )

    assert not warnings
    assert quiet_score is not None and threshold is not None
    assert quiet_evidence is not None
    assert deviant_score is not None
    # Breaking the learned Flow/Pressure correlation must score far higher
    # than a point consistent with it.
    assert deviant_score > quiet_score
    assert deviant_score >= threshold
