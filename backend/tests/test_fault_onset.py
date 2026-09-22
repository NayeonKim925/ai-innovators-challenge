from app.analytics.fault_onset import estimate_fault_onset
from app.domain import Capability, DatasetName, Incident, Observation, TimeRange


def incident() -> Incident:
    return Incident(
        id="case_1",
        source_dataset=DatasetName.CAUSRCA,
        title="Prepared incident",
        time_range_s=TimeRange(start=0, end=20),
        capabilities={Capability.TIME_SERIES},
        observations=[
            Observation(time_s=5, signal="HP_A_700304", value=False, kind="Alarm"),
            Observation(time_s=12, signal="HP_A_700304", value=True, kind="Alarm"),
            Observation(time_s=15, signal="LT_A_700317", value=True, kind="Alarm"),
        ],
    )


def test_estimate_fault_onset_returns_earliest_active_alarm() -> None:
    onset_time_s, evidence = estimate_fault_onset(incident(), up_to_time_s=20)

    assert onset_time_s == 12
    assert evidence is not None
    assert "HP_A_700304" in evidence.detail


def test_estimate_fault_onset_ignores_alarms_after_the_playback_position() -> None:
    onset_time_s, evidence = estimate_fault_onset(incident(), up_to_time_s=10)

    assert onset_time_s is None
    assert evidence is None


def test_estimate_fault_onset_returns_none_without_any_active_alarm() -> None:
    quiet = Incident(
        id="case_2",
        source_dataset=DatasetName.CAUSRCA,
        title="Normal operation",
        time_range_s=TimeRange(start=0, end=20),
        capabilities={Capability.TIME_SERIES},
        observations=[Observation(time_s=1, signal="HP_A_700304", value=False, kind="Alarm")],
    )

    onset_time_s, evidence = estimate_fault_onset(quiet, up_to_time_s=20)

    assert onset_time_s is None
    assert evidence is None
