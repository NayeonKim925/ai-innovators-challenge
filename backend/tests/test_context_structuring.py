"""Tests for proposal-only operator-note structuring."""

from pathlib import Path

from app.data.runtime_repository import JsonRuntimeRepository
from app.main import create_app
from fastapi.testclient import TestClient


def _client(tmp_path: Path) -> TestClient:
    runtime = tmp_path / "causrca"
    runtime.mkdir()
    (runtime / "incidents.json").write_text(
        "[{\"id\":\"case_1\",\"source_dataset\":\"causrca\","
        "\"title\":\"Test\",\"time_range_s\":{\"start\":0,\"end\":10},"
        "\"capabilities\":[\"time_series\"],"
        "\"observations\":[{\"time_s\":2,\"signal\":\"P101\","
        "\"value\":true,\"kind\":\"Alarm\"}]}]",
        encoding="utf-8",
    )
    return TestClient(create_app(JsonRuntimeRepository(tmp_path)))


def _open_case(client: TestClient) -> dict:
    response = client.post(
        "/api/incidents/case_1/cases",
        json={"diagnosis_time": 3, "question": "What should be verified?"},
    )
    assert response.status_code == 200
    return response.json()


def test_structuring_is_non_authoritative_until_one_proposal_is_accepted(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    case = _open_case(client)
    note = "Spindle vibration은 아직 확인하지 않았습니다. 다음 교대에서 확인 필요합니다."

    response = client.post(
        f"/api/cases/{case['id']}/structuring-proposals",
        json={
            "expected_version": case["version"],
            "note": note,
            "author": "Shift A",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_version"] == case["version"]
    assert {proposal["kind"] for proposal in payload["proposals"]} == {
        "observation",
        "open_item",
    }
    assert all(proposal["source_span"] == [0, len(note)] for proposal in payload["proposals"])
    unchanged = client.get(f"/api/cases/{case['id']}").json()
    assert unchanged["version"] == case["version"]
    assert unchanged["observations"] == []

    observation = next(item for item in payload["proposals"] if item["kind"] == "observation")
    accepted = client.post(
        f"/api/cases/{case['id']}/structuring-proposals/{observation['id']}/accept",
        json={"expected_version": case["version"], "accepted_by": "Shift B"},
    )

    assert accepted.status_code == 200
    updated = accepted.json()
    assert updated["version"] == case["version"] + 1
    assert updated["observations"][0]["original_text"] == note
    assert updated["events"][-1]["event_type"] == "observation_recorded"

    open_item = next(item for item in payload["proposals"] if item["kind"] == "open_item")
    stale_accept = client.post(
        f"/api/cases/{case['id']}/structuring-proposals/{open_item['id']}/accept",
        json={"expected_version": case["version"], "accepted_by": "Shift B"},
    )
    assert stale_accept.status_code == 409


def test_structuring_proposal_can_be_edited_before_acceptance(tmp_path: Path) -> None:
    client = _client(tmp_path)
    case = _open_case(client)
    response = client.post(
        f"/api/cases/{case['id']}/structuring-proposals",
        json={
            "expected_version": case["version"],
            "note": "Coolant 상태는 정상입니다.",
            "author": "Shift A",
        },
    )
    proposal = next(item for item in response.json()["proposals"] if item["kind"] == "observation")

    accepted = client.post(
        f"/api/cases/{case['id']}/structuring-proposals/{proposal['id']}/accept",
        json={
            "expected_version": case["version"],
            "accepted_by": "Shift B",
            "edited_text": "Coolant 압력과 상태를 현장에서 확인했고 정상으로 기록함.",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["observations"][0]["original_text"].startswith("Coolant 압력")
