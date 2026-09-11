from app.domain import Capability, DatasetName, Incident, Observation, TimeRange
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
        "prepare_human_review",
    ]


def test_workflow_abstains_without_active_alarm() -> None:
    result = investigate(incident(), diagnosis_time=9)

    assert result.candidates == []
    assert any("abstains" in warning for warning in result.warnings)
