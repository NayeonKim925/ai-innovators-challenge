from pathlib import Path

import pytest
from app.analytics import causrca_anomaly
from app.domain import Capability, DatasetName, Incident, Observation, TimeRange
from app.services.detection import run_auto_detection
from app.workflows.detection import detect_fault_onset


@pytest.fixture(autouse=True)
def _isolated_runtime_without_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test here must see "no PCA baseline available" by default -- otherwise
    a real `data/runtime/causrca/normal_baseline.json` prepared elsewhere on this
    machine (e.g. by running `scripts/prepare_causrca.py` for manual validation)
    would silently change these tests' anomaly-score branch outcomes."""
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "empty_runtime"))
    causrca_anomaly._MODEL_CACHE.clear()
    yield
    causrca_anomaly._MODEL_CACHE.clear()


def incident() -> Incident:
    return Incident(
        id="case_1",
        source_dataset=DatasetName.CAUSRCA,
        title="Prepared incident",
        time_range_s=TimeRange(start=0, end=20),
        capabilities={Capability.TIME_SERIES, Capability.ROOT_CAUSE_RANKING},
        observations=[
            Observation(time_s=12, signal="HP_A_700304", value=True, kind="Alarm"),
            Observation(time_s=13, signal="HP_Pump_Ok", value=False, kind="Measurement"),
        ],
    )


def test_detect_fault_onset_triggers_rca_when_an_alarm_is_active_and_pca_is_unavailable() -> None:
    """Phase 2 must not regress Phase 1: with no PCA baseline prepared, an
    active alarm alone is still enough to trigger RCA (`score is None` branch)."""
    result = detect_fault_onset(incident(), observed_up_to_s=20)

    assert result.decision == "trigger_rca"
    assert result.onset_time_s == 12
    assert result.anomaly_score is None
    assert len(result.evidence) == 1
    assert [event.tool for event in result.trace] == [
        "alarm_activation_onset_estimator",
        "pca_anomaly_score",
        "fault_detection_decision",
    ]


def test_detect_fault_onset_awaits_more_data_without_an_alarm() -> None:
    result = detect_fault_onset(incident(), observed_up_to_s=5)

    assert result.decision == "await_more_data"
    assert result.onset_time_s is None
    assert result.evidence == []


def test_run_auto_detection_hands_off_to_rca_with_renumbered_trace() -> None:
    detection, investigation = run_auto_detection(incident(), observed_up_to_s=20)

    assert detection.decision == "trigger_rca"
    assert investigation is not None
    assert investigation.diagnosis_time == detection.onset_time_s
    # Detection used steps 1-3 (alarm, PCA, decision); the investigation's
    # trace must continue from there, not repeat them.
    assert [event.step for event in investigation.trace] == [4, 5, 6, 7]
    assert any("fault-detection agent" in warning for warning in investigation.warnings)


def test_run_auto_detection_returns_no_investigation_without_a_detected_onset() -> None:
    quiet = Incident(
        id="case_2",
        source_dataset=DatasetName.CAUSRCA,
        title="Normal operation",
        time_range_s=TimeRange(start=0, end=20),
        capabilities={Capability.TIME_SERIES},
        observations=[Observation(time_s=1, signal="HP_A_700304", value=False, kind="Alarm")],
    )

    detection, investigation = run_auto_detection(quiet, observed_up_to_s=20)

    assert detection.decision == "await_more_data"
    assert investigation is None


def test_decide_next_action_flags_alarm_without_corroborating_anomaly_as_review() -> None:
    """When a PCA baseline IS available and disagrees with the alarm (score
    stays under the normal-operation threshold), the agent must not silently
    auto-trigger RCA -- it should ask a human to check for a false alarm."""
    from app.domain import TraceEvent
    from app.workflows.detection import decide_next_action

    state = {
        "onset_time_s": 12.0,
        "anomaly_score": 0.5,
        "anomaly_threshold": 10.0,
        "trace": [
            TraceEvent(step=1, tool="x", detail="x"),
            TraceEvent(step=2, tool="y", detail="y"),
        ],
    }

    result = decide_next_action(state)

    assert result["decision"] == "false_positive_review"


def test_decide_next_action_flags_high_anomaly_without_alarm_as_elevated_watch() -> None:
    from app.domain import TraceEvent
    from app.workflows.detection import decide_next_action

    state = {
        "onset_time_s": None,
        "anomaly_score": 50.0,
        "anomaly_threshold": 10.0,
        "trace": [
            TraceEvent(step=1, tool="x", detail="x"),
            TraceEvent(step=2, tool="y", detail="y"),
        ],
    }

    result = decide_next_action(state)

    assert result["decision"] == "elevated_watch"


def test_decide_next_action_triggers_rca_when_both_signals_agree() -> None:
    from app.domain import TraceEvent
    from app.workflows.detection import decide_next_action

    state = {
        "onset_time_s": 12.0,
        "anomaly_score": 50.0,
        "anomaly_threshold": 10.0,
        "trace": [
            TraceEvent(step=1, tool="x", detail="x"),
            TraceEvent(step=2, tool="y", detail="y"),
        ],
    }

    result = decide_next_action(state)

    assert result["decision"] == "trigger_rca"
