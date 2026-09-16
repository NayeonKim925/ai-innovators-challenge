"""Durable investigation storage with a local test-friendly fallback.

The API is stateless when it runs on Lambda.  The default in-memory repository
is useful for unit tests, but it must not be the only production option because
an invocation can land on a different Lambda worker.  This module keeps the
repository contract small and provides an optional DynamoDB implementation.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from ..domain import InvestigationResult, StoredReview
from .investigations import InMemoryInvestigationRepository


class InvestigationRepository(Protocol):
    def save(self, investigation_id: str, result: InvestigationResult) -> None: ...

    def get(self, investigation_id: str) -> InvestigationResult | None: ...

    def add_review(self, investigation_id: str, review: StoredReview) -> StoredReview: ...

    def list_reviews(self, investigation_id: str) -> list[StoredReview]: ...


class DynamoInvestigationRepository:
    """Stores one investigation per DynamoDB item.

    ``result_json`` and ``reviews_json`` keep the domain model independent of
    the persistence provider.  A conditional write prevents a review from
    being attached to an unknown investigation.  Review volume is low for the
    MVP; a later version can model reviews as separate sort-key items.
    """

    def __init__(self, table_name: str, region: str | None = None) -> None:
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:  # pragma: no cover - Lambda bundles boto3
            raise RuntimeError("DynamoDB storage requires boto3") from exc
        self._client_error = ClientError
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def save(self, investigation_id: str, result: InvestigationResult) -> None:
        self._table.put_item(
            Item={
                "investigation_id": investigation_id,
                "result_json": result.model_dump_json(),
                "reviews": [],
            }
        )

    def get(self, investigation_id: str) -> InvestigationResult | None:
        response = self._table.get_item(Key={"investigation_id": investigation_id})
        item = response.get("Item")
        if not item:
            return None
        return InvestigationResult.model_validate_json(item["result_json"])

    def add_review(self, investigation_id: str, review: StoredReview) -> StoredReview:
        try:
            response = self._table.update_item(
                Key={"investigation_id": investigation_id},
                UpdateExpression=(
                    "SET reviews = list_append(if_not_exists(reviews, :empty), :review)"
                ),
                ConditionExpression="attribute_exists(investigation_id)",
                ExpressionAttributeValues={
                    ":empty": [],
                    ":review": [json.loads(review.model_dump_json())],
                },
                ReturnValues="NONE",
            )
        except self._client_error as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                from .investigations import InvestigationNotFoundError

                raise InvestigationNotFoundError(investigation_id) from exc
            raise
        del response
        return review

    def list_reviews(self, investigation_id: str) -> list[StoredReview]:
        response = self._table.get_item(Key={"investigation_id": investigation_id})
        item = response.get("Item")
        if not item:
            return []
        reviews = item.get("reviews", [])
        if isinstance(reviews, str):  # backward compatibility with the first item shape
            reviews = json.loads(reviews)
        return [StoredReview.model_validate(value) for value in reviews]


def build_investigation_repository() -> InvestigationRepository:
    """Select durable storage when configured, otherwise keep local behavior."""

    table_name = os.getenv("INVESTIGATION_DDB_TABLE")
    if table_name:
        return DynamoInvestigationRepository(
            table_name=table_name,
            region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        )
    return InMemoryInvestigationRepository()
