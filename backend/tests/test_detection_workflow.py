from app.domain import Capability, DatasetName, Incident, Observation, TimeRange
from app.services.detection import run_auto_detection
from app.workflows.detection import detect_fault_onset


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


def test_detect_fault_onset_triggers_rca_when_an_alarm_is_active() -> None:
    result = detect_fault_onset(incident(), observed_up_to_s=20)

    assert result.decision == "trigger_rca"
    assert result.onset_time_s == 12
    assert result.evidence is not None
    assert [event.tool for event in result.trace] == [
        "alarm_activation_onset_estimator",
        "fault_detection_decision",
    ]


def test_detect_fault_onset_awaits_more_data_without_an_alarm() -> None:
    result = detect_fault_onset(incident(), observed_up_to_s=5)

    assert result.decision == "await_more_data"
    assert result.onset_time_s is None
    assert result.evidence is None


def test_run_auto_detection_hands_off_to_rca_with_renumbered_trace() -> None:
    detection, investigation = run_auto_detection(incident(), observed_up_to_s=20)

    assert detection.decision == "trigger_rca"
    assert investigation is not None
    assert investigation.diagnosis_time == detection.onset_time_s
    # Detection used steps 1-2; the investigation's trace must not repeat them.
    assert [event.step for event in investigation.trace] == [3, 4, 5, 6]
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
