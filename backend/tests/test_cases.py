"""Regression tests for the evidence-closure case contract.

These tests intentionally use only local runtime observations. They do not
load causRCA evaluation labels and do not call a real LLM provider.
"""

import json
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


def test_continuum_case_keeps_runs_and_open_items(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)

    assert case["schema_version"] == 2
    assert len(case["analysis_runs"]) == 1
    assert case["current_run_id"] == case["analysis_runs"][0]["id"]
    assert len(case["open_items"]) == 1
    assert case["tasks"][0]["open_item_id"] == case["open_items"][0]["id"]
    assert len(case["hypotheses"]) == 1

    observed = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "알람 이력은 확인했으나 현장 점검은 미실시",
            "author": "Shift A",
            "scope": "CNC-07",
            "provenance": "synthetic_demo",
        },
    )
    assert observed.status_code == 200
    observed_case = observed.json()
    assert len(observed_case["observations"]) == 1
    assert observed_case["events"][-1]["event_type"] == "observation_recorded"

    stale = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "오래된 화면에서 보낸 메모",
            "author": "Shift A",
            "provenance": "synthetic_demo",
        },
    )
    assert stale.status_code == 409

    rerun = client.post(
        f"/api/cases/{case['id']}/analysis-runs",
        json={
            "expected_version": observed_case["version"],
            "diagnosis_time": 4,
            "question": "새 관측 이후 다시 확인",
            "created_by": "Shift B",
        },
    )
    assert rerun.status_code == 200
    rerun_case = rerun.json()
    assert len(rerun_case["analysis_runs"]) == 2
    assert rerun_case["analysis_runs"][0]["investigation_id"] == case["investigation_id"]
    assert rerun_case["current_run_id"] == rerun_case["analysis_runs"][1]["id"]
    assert rerun_case["version"] == observed_case["version"] + 1


def test_unavailable_task_stays_open_as_open_item(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    task = case["tasks"][0]

    response = client.post(
        f"/api/cases/{case['id']}/tasks/{task['id']}/responses",
        json={
            "expected_version": case["version"],
            "outcome": "unavailable",
            "responder": "Shift A",
            "comment": "현장 접근 불가",
        },
    )

    assert response.status_code == 200
    result = response.json()
    item = next(item for item in result["open_items"] if item["id"] == task["open_item_id"])
    assert item["status"] == "unavailable"
    assert item["completion_note"] == "현장 접근 불가"


def test_handover_linter_publishes_snapshot_and_accepts_without_closing_case(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)

    blocked = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": case["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["findings"]

    observation = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "알람 이력은 확인했으나 현장 점검은 미실시",
            "author": "Shift A",
            "provenance": "synthetic_demo",
            "is_current_state": True,
        },
    ).json()
    item = observation["open_items"][0]
    assigned = client.post(
        f"/api/cases/{case['id']}/open-items/{item['id']}/updates",
        json={
            "expected_version": observation["version"],
            "status": "unavailable",
            "assignee": "Shift B",
            "completion_note": "다음 교대에서 확인 필요",
            "observation_ids": [observation["observations"][0]["id"]],
        },
    ).json()

    check = client.post(
        f"/api/cases/{case['id']}/handover-checks",
        json={
            "expected_version": assigned["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    )
    assert check.status_code == 200
    assert check.json()["blocking"] is False
    assert any(item["code"] == "unresolved-open-item" for item in check.json()["findings"])
    assert check.json()["case"]["events"][-1]["event_type"] == "handover_linted"

    checked = check.json()["case"]
    published_response = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": checked["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    )
    assert published_response.status_code == 200
    published = published_response.json()
    handover = published["handovers"][-1]
    snapshot = published["handover_snapshots"][-1]
    assert handover["status"] == "published"
    assert handover["source_case_version"] == checked["version"]
    assert snapshot["source_case_version"] == checked["version"]
    assert snapshot["open_item_ids"] == [item["id"]]
    assert snapshot["payload"]["case_id"] == case["id"]

    requested = client.post(
        f"/api/cases/{case['id']}/handovers/{handover['id']}/change-requests",
        json={
            "expected_version": published["version"],
            "requested_by": "Shift B",
            "reason": "현재 설비 상태 확인 시각을 설명해 주세요.",
        },
    )
    assert requested.status_code == 200
    requested_case = requested.json()
    assert requested_case["handovers"][-1]["status"] == "changes_requested"
    assert "clarify" in requested_case["next_action"]

    republished_response = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": requested_case["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    )
    assert republished_response.status_code == 200
    published = republished_response.json()
    handover = published["handovers"][-1]
    snapshot = published["handover_snapshots"][-1]

    accepted_response = client.post(
        f"/api/cases/{case['id']}/handovers/{handover['id']}/acceptance",
        json={
            "expected_version": published["version"],
            "snapshot_id": snapshot["id"],
            "accepted_by": "Shift B",
        },
    )
    assert accepted_response.status_code == 200
    accepted = accepted_response.json()
    assert accepted["handovers"][-1]["status"] == "accepted"
    assert accepted["status"] == "awaiting_evidence"


def test_handover_exception_requires_authenticated_lead(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)

    denied = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": case["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
            "exception_reason": "긴급 교대라서 우선 전달",
        },
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/cases/{case['id']}/handovers",
        headers={"X-Actor-Id": "lead-1", "X-Actor-Role": "shift_lead"},
        json={
            "expected_version": case["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
            "exception_reason": "긴급 교대라서 우선 전달",
        },
    )
    assert allowed.status_code == 200
    handover = allowed.json()["handovers"][-1]
    assert handover["exception_approved_by"] == "lead-1"
    assert handover["exception_approved_role"] == "shift_lead"


def test_handover_requires_explicit_current_state_observation(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    observed = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "과거 점검 메모",
            "author": "Shift A",
            "provenance": "synthetic_demo",
            "is_current_state": False,
        },
    ).json()

    blocked = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": observed["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    )
    assert blocked.status_code == 409
    assert any(
        finding["code"] == "missing-current-state"
        for finding in blocked.json()["detail"]["findings"]
    )


def test_stale_handover_snapshot_is_superseded_before_acceptance(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    observed = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "교대 메모",
            "author": "Shift A",
            "provenance": "synthetic_demo",
            "is_current_state": True,
        },
    ).json()
    item = observed["open_items"][0]
    assigned = client.post(
        f"/api/cases/{case['id']}/open-items/{item['id']}/updates",
        json={
            "expected_version": observed["version"],
            "status": "unavailable",
            "assignee": "Shift B",
            "observation_ids": [observed["observations"][0]["id"]],
        },
    ).json()
    published = client.post(
        f"/api/cases/{case['id']}/handovers",
        json={
            "expected_version": assigned["version"],
            "sender": "Shift A",
            "receiver": "Shift B",
        },
    ).json()
    snapshot = published["handover_snapshots"][-1]
    changed = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": published["version"],
            "original_text": "인계 발행 후 새 관측",
            "author": "Shift B",
            "provenance": "synthetic_demo",
        },
    ).json()
    resume = client.get(f"/api/cases/{case['id']}/resume").json()
    assert any(item["kind"] == "case-version-changed" for item in resume["handover_delta"])

    stale_accept = client.post(
        f"/api/cases/{case['id']}/handovers/{published['handovers'][-1]['id']}/acceptance",
        json={
            "expected_version": changed["version"],
            "snapshot_id": snapshot["id"],
            "accepted_by": "Shift B",
        },
    )
    assert stale_accept.status_code == 409
    current = client.get(f"/api/cases/{case['id']}").json()
    assert current["handovers"][-1]["status"] == "superseded"


def test_case_resume_and_qna_use_current_case_state_without_llm(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    observed = client.post(
        f"/api/cases/{case['id']}/observations",
        json={
            "expected_version": case["version"],
            "original_text": "알람 이력 확인 완료, 현장 점검은 미실시",
            "author": "Shift A",
            "provenance": "synthetic_demo",
            "is_current_state": True,
        },
    )
    assert observed.status_code == 200

    resume = client.get(f"/api/cases/{case['id']}/resume")
    assert resume.status_code == 200
    resume_body = resume.json()
    assert resume_body["case_id"] == case["id"]
    assert resume_body["observations"][0]["text"].startswith("알람 이력")
    assert resume_body["observations"][0]["is_current_state"] is True
    assert resume_body["open_items"]

    answer = client.post(
        f"/api/cases/{case['id']}/chat",
        json={"question": "지금까지 무엇을 확인했고 무엇이 남았나요?"},
    )
    assert answer.status_code == 200
    body = answer.json()
    assert "알람 이력 확인 완료" in body["answer"]
    assert "현장 점검" in body["answer"]
    assert body["llm_status"] == "not_requested"
    assert body["trace"]["tool"] == "case_resume_template"


def test_case_qna_llm_failure_keeps_template_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.case_chat as chat_module
    from app.domain import TraceEvent

    monkeypatch.setattr(
        chat_module,
        "generate_narrative",
        lambda _result: (
            None,
            TraceEvent(
                step=5,
                tool="bedrock_narrative_unverified",
                detail="forced test fallback",
            ),
        ),
    )
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    answer = client.post(
        f"/api/cases/{case['id']}/chat",
        json={"question": "왜 이 후보인가요?", "include_llm": True},
    )

    assert answer.status_code == 200
    body = answer.json()
    assert "P101" in body["answer"]
    assert body["llm_status"] == "unverified"
    assert body["trace"]["tool"] == "bedrock_narrative_unverified"


def test_unresolved_open_item_blocks_case_close(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    task = case["tasks"][0]
    ready = client.post(
        f"/api/cases/{case['id']}/tasks/{task['id']}/responses",
        json={
            "outcome": "confirmed",
            "responder": "Jin",
            "comment": "근거 확인",
        },
    ).json()
    extra = client.post(
        f"/api/cases/{case['id']}/open-items",
        json={
            "expected_version": ready["version"],
            "title": "추가 현장 확인",
            "requested_role": "operator",
        },
    ).json()

    blocked = client.post(
        f"/api/cases/{case['id']}/reviews",
        json={"decision": "approve", "reviewer": "Jin", "comment": "검토"},
    )
    assert blocked.status_code == 409
    assert "Open Items" in blocked.json()["detail"]

    resolved = client.post(
        f"/api/cases/{case['id']}/open-items/{extra['open_items'][-1]['id']}/updates",
        json={
            "expected_version": extra["version"],
            "status": "resolved",
            "completion_note": "현장 확인 기록 첨부",
        },
    )
    assert resolved.status_code == 200
    closed = client.post(
        f"/api/cases/{case['id']}/reviews",
        json={"decision": "approve", "reviewer": "Jin", "comment": "검토"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


def test_case_rejects_unknown_evidence_reference(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    response = client.post(
        f"/api/cases/{case['id']}/open-items",
        json={
            "expected_version": case["version"],
            "title": "허위 근거 참조",
            "requested_role": "operator",
            "evidence_ids": ["E999"],
        },
    )
    assert response.status_code == 409


def test_analysis_run_idempotency_returns_existing_case_without_duplicate_run(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    request = {
        "expected_version": case["version"],
        "diagnosis_time": 4,
        "question": "재현 가능한 후속 분석",
        "created_by": "Shift B",
        "idempotency_key": "resume-case-1",
    }
    first = client.post(f"/api/cases/{case['id']}/analysis-runs", json=request)
    assert first.status_code == 200
    second = client.post(f"/api/cases/{case['id']}/analysis-runs", json=request)
    assert second.status_code == 200
    assert second.json()["version"] == first.json()["version"]
    assert len(second.json()["analysis_runs"]) == len(first.json()["analysis_runs"]) == 2


def test_dynamo_case_repository_projects_legacy_json_to_first_analysis_run(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    current = _open_case(client)
    legacy_payload = json.loads(json.dumps(current))
    for field in (
        "schema_version",
        "current_run_id",
        "analysis_runs",
        "observations",
        "open_items",
        "hypotheses",
        "handover_snapshots",
        "handovers",
        "current_handover_id",
    ):
        legacy_payload.pop(field, None)
    for task in legacy_payload["tasks"]:
        task.pop("open_item_id", None)

    repository = object.__new__(DynamoCaseRepository)
    repository._table = _FakeCaseTable()
    repository._client_error = RuntimeError
    repository._table.items[current["id"]] = {
        "case_id": current["id"],
        "case_json": json.dumps(legacy_payload),
        "updated_at": current["updated_at"],
        "version": current["version"],
    }

    loaded = repository.get(current["id"])
    assert loaded is not None
    assert loaded.schema_version == 2
    assert len(loaded.analysis_runs) == 1
    assert loaded.analysis_runs[0].investigation_id == current["investigation_id"]
    assert loaded.current_run_id == loaded.analysis_runs[0].id
    assert loaded.investigation_id == current["investigation_id"]


def test_case_observation_rejects_second_write_from_same_stale_version(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        '[{"time_s":2,"signal":"P101","value":true,"kind":"Alarm"}]',
    )
    case = _open_case(client)
    body = {
        "expected_version": case["version"],
        "original_text": "첫 번째 교대 관찰",
        "author": "Shift A",
        "provenance": "synthetic_demo",
    }
    first = client.post(f"/api/cases/{case['id']}/observations", json=body)
    second = client.post(f"/api/cases/{case['id']}/observations", json=body)
    assert first.status_code == 200
    assert second.status_code == 409
