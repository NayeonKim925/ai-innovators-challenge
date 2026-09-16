"""AWS Lambda handler for the durable Bedrock narrative queue."""

from __future__ import annotations

import json

from app.repositories.investigation_store import build_investigation_repository
from app.services.narrative_jobs import process_narrative_job


def handler(event: dict, _context: object) -> dict[str, int]:
    repository = build_investigation_repository()
    processed = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        process_narrative_job(repository, body["investigation_id"])
        processed += 1
    return {"processed": processed}

