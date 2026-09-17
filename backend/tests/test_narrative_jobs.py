from app.domain import Capability, DatasetName, Incident, Observation, TimeRange, TraceEvent
from app.repositories.investigations import InMemoryInvestigationRepository
from app.services.investigations import run_investigation
from app.services.narrative_jobs import process_narrative_job


def test_narrative_worker_updates_only_the_stored_investigation(monkeypatch) -> None:
    incident = Incident(
        id="case_worker",
        source_dataset=DatasetName.CAUSRCA,
        title="worker test",
        time_range_s=TimeRange(start=0, end=10),
        capabilities={Capability.TIME_SERIES},
        observations=[Observation(time_s=2, signal="P101", value=True, kind="Alarm")],
    )
    result = run_investigation(incident, 3, "왜 이 신호인가요?", False)
    repository = InMemoryInvestigationRepository()
    repository.save("investigation-1", result)

    import app.services.narrative_jobs as jobs

    monkeypatch.setattr(
        jobs,
        "generate_narrative",
        lambda _result: (
            "[E1] P101은 확인이 필요한 후보입니다.",
            TraceEvent(step=5, tool="bedrock_llm_narrative", detail="test"),
        ),
    )

    finished = process_narrative_job(repository, "investigation-1")

    assert finished.llm_status.value == "generated"
    assert finished.mode == "deterministic_with_llm_narrative"
    assert repository.get("investigation-1").llm_narrative.startswith("[E1]")
