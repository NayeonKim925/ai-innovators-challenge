from pathlib import Path

from fastapi.testclient import TestClient

from app.data.runtime_repository import JsonRuntimeRepository
from app.main import create_app


def test_api_lists_and_investigates_runtime_incident(tmp_path: Path) -> None:
    runtime = tmp_path / "causrca"
    runtime.mkdir()
    (runtime / "incidents.json").write_text(
        '[{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},"capabilities":["time_series"],'
        '"observations":[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]}]',
        encoding="utf-8",
    )
    client = TestClient(create_app(JsonRuntimeRepository(tmp_path)))

    assert client.get("/api/incidents").json()["incidents"][0]["id"] == "case_1"
    result = client.post(
        "/api/incidents/case_1/investigations",
        json={"diagnosis_time": 3, "question": "What should we check?"},
    )

    assert result.status_code == 200
    assert result.json()["candidates"][0]["signal"] == "P101"
