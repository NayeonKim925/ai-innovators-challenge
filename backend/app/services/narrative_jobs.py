"""Durable queue boundary for optional Bedrock narrative generation."""

from __future__ import annotations

import json
import os
from typing import Any

from ..domain import InvestigationResult, LLMStatus, TraceEvent
from ..llm.explainer import generate_narrative
from ..repositories.investigation_store import InvestigationRepository
from ..repositories.investigations import InvestigationNotFoundError


class NarrativeQueueUnavailable(RuntimeError):
    """Raised when asynchronous narratives are requested without an SQS queue."""


def enqueue_narrative_job(investigation_id: str) -> str:
    queue_url = os.getenv("LLM_JOB_QUEUE_URL")
    if not queue_url:
        raise NarrativeQueueUnavailable("LLM_JOB_QUEUE_URL is not configured")
    try:
        import boto3

        response = boto3.client(
            "sqs", region_name=os.getenv("AWS_REGION", "us-east-1")
        ).send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"investigation_id": investigation_id}),
        )
    except Exception as exc:  # pragma: no cover - exercised by AWS integration
        raise NarrativeQueueUnavailable("SQS narrative job could not be queued") from exc
    return str(response.get("MessageId", ""))


def mark_queued(result: InvestigationResult) -> InvestigationResult:
    return result.model_copy(
        update={
            "llm_status": LLMStatus.QUEUED,
            "trace": [
                *result.trace,
                TraceEvent(
                    step=5,
                    tool="llm_narrative_queued",
                    detail=(
                        "Bedrock narrative was queued; deterministic findings remain "
                        "available immediately."
                    ),
                ),
            ],
        }
    )


def process_narrative_job(
    repository: InvestigationRepository, investigation_id: str
) -> InvestigationResult:
    """Generate and persist one narrative from the authoritative result."""
    result = repository.get(investigation_id)
    if result is None:
        raise InvestigationNotFoundError(investigation_id)
    running = result.model_copy(update={"llm_status": LLMStatus.RUNNING})
    repository.replace(investigation_id, running)
    narrative, trace_event = generate_narrative(running)
    updates: dict[str, Any] = {"trace": [*running.trace, trace_event]}
    if narrative is not None:
        updates.update(
            {
                "mode": "deterministic_with_llm_narrative",
                "llm_narrative": narrative,
                "llm_status": LLMStatus.GENERATED,
            }
        )
    else:
        updates["llm_status"] = {
            "bedrock_guardrail_blocked": LLMStatus.BLOCKED,
            "bedrock_narrative_unverified": LLMStatus.UNVERIFIED,
        }.get(trace_event.tool, LLMStatus.UNAVAILABLE)
    finished = running.model_copy(update=updates)
    repository.replace(investigation_id, finished)
    return finished
