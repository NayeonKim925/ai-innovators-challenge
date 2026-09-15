from pathlib import Path

from app.data.runtime_repository import JsonRuntimeRepository
from app.main import create_app
from fastapi.testclient import TestClient


def _client_with_prepared_incident(tmp_path: Path) -> TestClient:
    runtime = tmp_path / "causrca"
    runtime.mkdir()
    (runtime / "incidents.json").write_text(
        '[{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},"capabilities":["time_series"],'
        '"observations":[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]}]',
        encoding="utf-8",
    )
    return TestClient(create_app(JsonRuntimeRepository(tmp_path)))


def test_api_lists_and_investigates_runtime_incident(tmp_path: Path) -> None:
    client = _client_with_prepared_incident(tmp_path)

    assert client.get("/api/incidents").json()["incidents"][0]["id"] == "case_1"
    result = client.post(
        "/api/incidents/case_1/investigations",
        json={"diagnosis_time": 3, "question": "What should we check?"},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["candidates"][0]["signal"] == "P101"
    assert body["mode"] == "deterministic"
    assert body["llm_narrative"] is None
    assert isinstance(body["investigation_id"], str) and body["investigation_id"]


def test_api_investigation_review_and_report_roundtrip(tmp_path: Path) -> None:
    """2-A: POST investigations -> GET investigations/{id} -> POST reviews ->
    GET report must all round-trip through the same in-memory store."""
    client = _client_with_prepared_incident(tmp_path)

    created = client.post(
        "/api/incidents/case_1/investigations",
        json={"diagnosis_time": 3, "question": ""},
    )
    investigation_id = created.json()["investigation_id"]

    fetched = client.get(f"/api/investigations/{investigation_id}")
    assert fetched.status_code == 200
    assert fetched.json()["incident_id"] == "case_1"

    review = client.post(
        f"/api/investigations/{investigation_id}/reviews",
        json={"decision": "approve", "comment": "Looks right.", "reviewer": "Alice"},
    )
    assert review.status_code == 200
    assert review.json()["decision"] == "approve"
    assert review.json()["reviewer"] == "Alice"

    report = client.get(f"/api/investigations/{investigation_id}/report")
    assert report.status_code == 200
    report_body = report.json()
    assert report_body["investigation_id"] == investigation_id
    assert report_body["result"]["candidates"][0]["signal"] == "P101"
    assert len(report_body["reviews"]) == 1
    assert report_body["reviews"][0]["decision"] == "approve"


def test_api_review_on_unknown_investigation_returns_404(tmp_path: Path) -> None:
    client = _client_with_prepared_incident(tmp_path)

    response = client.post(
        "/api/investigations/does-not-exist/reviews",
        json={"decision": "approve", "comment": "", "reviewer": "Alice"},
    )

    assert response.status_code == 404


def test_api_report_on_unknown_investigation_returns_404(tmp_path: Path) -> None:
    client = _client_with_prepared_incident(tmp_path)

    assert client.get("/api/investigations/does-not-exist/report").status_code == 404


def test_api_investigation_with_llm_narrative_flag_falls_back_offline(
    tmp_path: Path, monkeypatch
) -> None:
    """include_llm_narrative=True must never crash and must never call the
    real Bedrock API in tests -- force build_client() to fail, same pattern
    as test_llm_narrative.py."""
    import app.llm.explainer as explainer_module
    from app.llm.bedrock_client import BedrockUnavailable

    def _always_unavailable() -> None:
        raise BedrockUnavailable("forced for test: no real network call is made")

    monkeypatch.setattr(explainer_module, "build_client", _always_unavailable)
    client = _client_with_prepared_incident(tmp_path)

    result = client.post(
        "/api/incidents/case_1/investigations",
        json={"diagnosis_time": 3, "question": "", "include_llm_narrative": True},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["mode"] == "deterministic"
    assert body["llm_narrative"] is None
    assert body["trace"][-1]["tool"] == "bedrock_llm_narrative"
