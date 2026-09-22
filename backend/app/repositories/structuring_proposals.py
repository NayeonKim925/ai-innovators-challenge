"""Persistence boundary for non-authoritative structuring proposals."""

from __future__ import annotations

import os
from typing import Protocol

from ..domain import StructuringProposal


class StructuringProposalRepository(Protocol):
    """Store reviewable proposals without mixing them into the Case aggregate."""

    def save(self, proposal: StructuringProposal) -> None: ...

    def get(self, proposal_id: str) -> StructuringProposal | None: ...

    def list_for_case(self, case_id: str) -> list[StructuringProposal]: ...

    def delete(self, proposal_id: str) -> None: ...


class InMemoryStructuringProposalRepository:
    """Small local repository used by tests and the deterministic research UI."""

    def __init__(self) -> None:
        self._proposals: dict[str, StructuringProposal] = {}

    def save(self, proposal: StructuringProposal) -> None:
        self._proposals[proposal.id] = proposal

    def get(self, proposal_id: str) -> StructuringProposal | None:
        return self._proposals.get(proposal_id)

    def list_for_case(self, case_id: str) -> list[StructuringProposal]:
        return sorted(
            (item for item in self._proposals.values() if item.case_id == case_id),
            key=lambda item: item.created_at,
        )

    def delete(self, proposal_id: str) -> None:
        self._proposals.pop(proposal_id, None)


class DynamoStructuringProposalRepository:
    """DynamoDB-backed proposal storage for multi-worker deployments."""

    def __init__(self, table_name: str, region: str | None = None) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - Lambda bundles boto3
            raise RuntimeError("DynamoDB storage requires boto3") from exc
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def save(self, proposal: StructuringProposal) -> None:
        self._table.put_item(
            Item={
                "proposal_id": proposal.id,
                "case_id": proposal.case_id,
                "created_at": proposal.created_at,
                "proposal_json": proposal.model_dump_json(),
            }
        )

    def get(self, proposal_id: str) -> StructuringProposal | None:
        response = self._table.get_item(Key={"proposal_id": proposal_id})
        item = response.get("Item")
        return StructuringProposal.model_validate_json(item["proposal_json"]) if item else None

    def list_for_case(self, case_id: str) -> list[StructuringProposal]:
        items: list[dict[str, object]] = []
        start_key: dict[str, object] | None = None
        while True:
            kwargs: dict[str, object] = {
                "FilterExpression": "case_id = :case_id",
                "ExpressionAttributeValues": {":case_id": case_id},
                "ProjectionExpression": "proposal_json",
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        proposals = [
            StructuringProposal.model_validate_json(item["proposal_json"])
            for item in items
        ]
        return sorted(proposals, key=lambda item: item.created_at)

    def delete(self, proposal_id: str) -> None:
        self._table.delete_item(Key={"proposal_id": proposal_id})


def build_structuring_proposal_repository() -> StructuringProposalRepository:
    """Use durable storage when configured; preserve local behavior otherwise."""

    table_name = os.getenv("STRUCTURING_PROPOSAL_DDB_TABLE")
    if table_name:
        return DynamoStructuringProposalRepository(
            table_name=table_name,
            region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        )
    return InMemoryStructuringProposalRepository()
