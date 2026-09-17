"""Regression tests for the evidence-closure case contract.

These tests intentionally use only local runtime observations. They do not
load causRCA evaluation labels and do not call a real LLM provider.
"""

from pathlib import Path

import pytest
from app.data.runtime_repository import JsonRuntimeRepository
from app.domain import InvestigationCase
from app.main import create_app
from app.repositories.cases import CaseConflictError, DynamoCaseRepository, InMemoryCaseRepository
from fastapi.testclient import TestClient


def _client(tmp_path: Path, observations: str) -> TestClient:
    runtime = tmp_path / "causrca"
    runtime.mkdir()
    (runtime / "incidents.json").write_text(
        "["
        '{"id":"case_1","source_dataset":"causrca","title":"Test",'
        '"time_range_s":{"start":0,"end":10},'
        '"capabilities":["time_series"],'
        f'"observations":{observations}'
        "}]",
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


def test_case_needs_evidence_response_then_explicit_review_to_close(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)

    assert case["status"] == "awaiting_evidence"
    assert case["tasks"][0]["kind"] == "verify_candidate"
    assert case["tasks"][0]["evidence_ids"] == ["E1"]
    assert case["events"][0]["event_type"] == "analysis_completed"

    premature = client.post(
        f"/api/cases/{case['id']}/reviews",
        json={"decision": "approve", "reviewer": "Jin", "comment": "too early"},
    )
    assert premature.status_code == 409

    response = client.post(
        f"/api/cases/{case['id']}/tasks/{case['tasks'][0]['id']}/responses",
        json={"outcome": "confirmed", "responder": "Jin", "comment": "Signal is observable."},
    )
    assert response.status_code == 200
    review_ready = response.json()
    assert review_ready["status"] == "ready_for_review"
    assert review_ready["tasks"][0]["status"] == "completed"
    assert review_ready["tasks"][0]["response"]["outcome"] == "confirmed"
    assert review_ready["events"][-1]["event_type"] == "case_ready_for_review"

    closed = client.post(
        f"/api/cases/{case['id']}/reviews",
        json={"decision": "approve", "reviewer": "Jin", "comment": "Reviewed."},
    )
    assert closed.status_code == 200
    result = closed.json()
    assert result["status"] == "closed"
    assert result["reviews"][0]["decision"] == "approve"
    assert result["events"][-1]["event_type"] == "case_closed"


def test_refuted_candidate_reopens_case_and_requests_observation(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)

    response = client.post(
        f"/api/cases/{case['id']}/tasks/{case['tasks'][0]['id']}/responses",
        json={"outcome": "refuted", "responder": "Jin", "comment": "Not supported in logbook."},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "reopened"
    assert len(result["tasks"]) == 2
    assert result["tasks"][1]["kind"] == "collect_observation"
    assert result["tasks"][1]["status"] == "pending"
    assert any(event["event_type"] == "case_reopened" for event in result["events"])
    assert all(event["event_type"] != "case_closed" for event in result["events"])


def test_case_abstains_after_missing_candidate_requests_observation(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"TEMP","value":1.0,"kind":"Measurement"}]',
    )
    case = _open_case(client)

    assert case["status"] == "awaiting_evidence"
    assert case["tasks"][0]["kind"] == "collect_observation"

    response = client.post(
        f"/api/cases/{case['id']}/tasks/{case['tasks'][0]['id']}/responses",
        json={"outcome": "confirmed", "responder": "Jin", "comment": "Extra context recorded."},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "abstained"
    assert result["events"][-1]["event_type"] == "case_abstained"
    assert all(event["event_type"] != "case_closed" for event in result["events"])


class _FakeCaseTable:
    """Tiny DynamoDB table double that also exercises scan pagination."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}

    def put_item(self, **kwargs: object) -> None:
        item = kwargs["Item"]
        assert isinstance(item, dict)
        self.items[item["case_id"]] = item

    def get_item(self, **kwargs: object) -> dict[str, object]:
        key = kwargs["Key"]
        assert isinstance(key, dict)
        item = self.items.get(key["case_id"])
        return {"Item": item} if item else {}

    def update_item(self, **kwargs: object) -> None:
        key = kwargs["Key"]
        values = kwargs["ExpressionAttributeValues"]
        assert isinstance(key, dict)
        assert isinstance(values, dict)
        item = self.items[key["case_id"]]
        assert item["version"] == values[":expected_version"]
        item["case_json"] = values[":case_json"]
        item["updated_at"] = values[":updated_at"]
        item["version"] = values[":next_version"]

    def scan(self, **kwargs: object) -> dict[str, object]:
        ordered = [self.items[key] for key in sorted(self.items)]
        start_key = kwargs.get("ExclusiveStartKey")
        start = 0
        if start_key:
            assert isinstance(start_key, dict)
            start = next(
                index
                for index, item in enumerate(ordered)
                if item["case_id"] == start_key["case_id"]
            ) + 1
        page = ordered[start : start + 1]
        response: dict[str, object] = {"Items": page}
        if start + 1 < len(ordered):
            response["LastEvaluatedKey"] = {"case_id": page[-1]["case_id"]}
        return response


def test_dynamo_case_repository_round_trips_and_paginates(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    first = InvestigationCase.model_validate(_open_case(client))
    second = first.model_copy(
        update={"id": "case_second", "updated_at": "2099-01-01T00:00:00+00:00"}
    )
    repository = object.__new__(DynamoCaseRepository)
    repository._table = _FakeCaseTable()
    repository._client_error = RuntimeError

    repository.save(first)
    repository.save(second)
    loaded = repository.get(first.id)

    assert loaded is not None
    assert loaded.id == first.id
    assert [item.id for item in repository.list()] == [second.id, first.id]

    updated = first.model_copy(
        update={
            "next_action": "Review required",
            "updated_at": "2098-01-01T00:00:00+00:00",
            "version": first.version + 1,
        }
    )
    repository.replace(updated, expected_version=first.version)
    assert repository.get(first.id).next_action == "Review required"


def test_case_repository_rejects_stale_transition(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    original = InvestigationCase.model_validate(_open_case(client))
    repository = InMemoryCaseRepository()
    repository.save(original)

    first_reader = repository.get(original.id)
    stale_reader = repository.get(original.id)
    assert first_reader is not None
    assert stale_reader is not None

    repository.replace(
        first_reader.model_copy(update={"version": first_reader.version + 1}),
        expected_version=first_reader.version,
    )
    with pytest.raises(CaseConflictError):
        repository.replace(
            stale_reader.model_copy(update={"version": stale_reader.version + 1}),
            expected_version=stale_reader.version,
        )
