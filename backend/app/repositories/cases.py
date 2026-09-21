"""Persistence boundary for evidence-closure cases.

Case state must survive Lambda worker changes. The local in-memory repository
remains the default for tests and research, while ``CASE_DDB_TABLE`` enables a
small, independent DynamoDB table in a deployed environment. Case and
investigation records intentionally use different tables because their primary
keys and access patterns are different.
"""

from __future__ import annotations

import os
from typing import Protocol

from ..domain import AnalysisRun, InvestigationCase


def _read_case(payload: object) -> InvestigationCase:
    """Read v1 Case JSON without rewriting the stored legacy record."""

    case = (
        InvestigationCase.model_validate_json(payload)
        if isinstance(payload, str)
        else InvestigationCase.model_validate(payload)
    )
    if not case.analysis_runs and case.investigation_id:
        legacy_run = AnalysisRun(
            id=f"run_legacy_{case.investigation_id}",
            investigation_id=case.investigation_id,
            incident_id=case.incident_id,
            dataset=case.dataset,
            diagnosis_time=0,
            algorithm_version="legacy-unknown",
            created_by="legacy_reader",
            created_at=case.created_at,
        )
        case = case.model_copy(
            update={
                "analysis_runs": [legacy_run],
                "current_run_id": legacy_run.id,
            }
        )

    def run_at(created_at: str) -> str | None:
        earlier = [run for run in case.analysis_runs if run.created_at <= created_at]
        if earlier:
            return max(earlier, key=lambda run: run.created_at).id
        return case.analysis_runs[0].id if case.analysis_runs else case.current_run_id

    tasks = [
        task
        if task.run_id is not None
        else task.model_copy(update={"run_id": run_at(task.created_at)})
        for task in case.tasks
    ]
    task_run_by_item = {
        task.open_item_id: task.run_id for task in tasks if task.open_item_id is not None
    }
    open_items = [
        item
        if item.run_id is not None
        else item.model_copy(
            update={"run_id": task_run_by_item.get(item.id) or run_at(item.created_at)}
        )
        for item in case.open_items
    ]
    return case.model_copy(
        update={
            "schema_version": max(case.schema_version, 3),
            "tasks": tasks,
            "open_items": open_items,
        }
    )


class CaseNotFoundError(LookupError):
    """Raised when a caller references a case that was never stored."""


class CaseAlreadyExistsError(RuntimeError):
    """Raised when a new case ID collides with an existing record."""


class CaseConflictError(RuntimeError):
    """Raised when a case changed after the caller read it."""


class CaseRepository(Protocol):
    def save(self, case: InvestigationCase) -> None: ...

    def replace(self, case: InvestigationCase, *, expected_version: int) -> None: ...

    def get(self, case_id: str) -> InvestigationCase | None: ...

    def list(self) -> list[InvestigationCase]: ...


class InMemoryCaseRepository:
    """Test-friendly storage for stateful cases during local development."""

    def __init__(self) -> None:
        self._cases: dict[str, InvestigationCase] = {}

    def save(self, case: InvestigationCase) -> None:
        if case.id in self._cases:
            raise CaseAlreadyExistsError(case.id)
        self._cases[case.id] = case

    def replace(self, case: InvestigationCase, *, expected_version: int) -> None:
        current = self._cases.get(case.id)
        if current is None:
            raise CaseNotFoundError(case.id)
        if current.version != expected_version:
            raise CaseConflictError(case.id)
        if case.version != expected_version + 1:
            raise ValueError("Replacement case version must increment by one")
        self._cases[case.id] = case

    def get(self, case_id: str) -> InvestigationCase | None:
        return self._cases.get(case_id)

    def list(self) -> list[InvestigationCase]:
        return sorted(self._cases.values(), key=lambda item: item.updated_at, reverse=True)


class DynamoCaseRepository:
    """Stores one evidence-closure case per DynamoDB item.

    The serialized domain model keeps DynamoDB-specific types away from the
    orchestration service. ``list`` is a paginated scan because the MVP has no
    organization or assignee partition yet; it is safe for the small research
    workspace but should be replaced by an indexed, tenant-scoped query before
    multi-organization operation.
    """

    def __init__(self, table_name: str, region: str | None = None) -> None:
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:  # pragma: no cover - Lambda bundles boto3
            raise RuntimeError("DynamoDB storage requires boto3") from exc
        self._client_error = ClientError
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def save(self, case: InvestigationCase) -> None:
        try:
            self._table.put_item(
                Item={
                    "case_id": case.id,
                    "case_json": case.model_dump_json(),
                    "updated_at": case.updated_at,
                    "version": case.version,
                },
                ConditionExpression="attribute_not_exists(case_id)",
            )
        except self._client_error as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise CaseAlreadyExistsError(case.id) from exc
            raise

    def replace(self, case: InvestigationCase, *, expected_version: int) -> None:
        if case.version != expected_version + 1:
            raise ValueError("Replacement case version must increment by one")
        try:
            self._table.update_item(
                Key={"case_id": case.id},
                UpdateExpression=(
                    "SET case_json = :case_json, updated_at = :updated_at, #version = :next_version"
                ),
                ConditionExpression="attribute_exists(case_id) AND #version = :expected_version",
                ExpressionAttributeNames={"#version": "version"},
                ExpressionAttributeValues={
                    ":case_json": case.model_dump_json(),
                    ":updated_at": case.updated_at,
                    ":expected_version": expected_version,
                    ":next_version": case.version,
                },
            )
        except self._client_error as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise CaseConflictError(case.id) from exc
            raise

    def get(self, case_id: str) -> InvestigationCase | None:
        response = self._table.get_item(Key={"case_id": case_id})
        item = response.get("Item")
        if not item:
            return None
        return _read_case(item["case_json"])

    def list(self) -> list[InvestigationCase]:
        items: list[dict[str, object]] = []
        start_key: dict[str, object] | None = None
        while True:
            kwargs: dict[str, object] = {"ProjectionExpression": "case_json"}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        cases = [_read_case(item["case_json"]) for item in items]
        return sorted(cases, key=lambda item: item.updated_at, reverse=True)


def build_case_repository() -> CaseRepository:
    """Choose durable case storage when configured, otherwise preserve local mode."""

    table_name = os.getenv("CASE_DDB_TABLE")
    if table_name:
        return DynamoCaseRepository(
            table_name=table_name,
            region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        )
    return InMemoryCaseRepository()
