"""HTTP boundary for the local research MVP."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data.runtime_repository import JsonRuntimeRepository
from .domain import (
    ChatRequest,
    DatasetName,
    InvestigationReport,
    InvestigationRequest,
    ReviewDecision,
    StoredReview,
)
from .repositories.investigation_store import (
    InvestigationRepository,
    build_investigation_repository,
)
from .repositories.investigations import InvestigationNotFoundError
from .services.investigations import answer_question, run_investigation


def create_app(
    repository: JsonRuntimeRepository | None = None,
    investigations: InvestigationRepository | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Manufacturing Investigation API",
        version="0.2.0",
        description="Evidence-linked incident investigation service. It does not control equipment.",
    )
    app.state.repository = repository or JsonRuntimeRepository()
    app.state.investigations = investigations or build_investigation_repository()
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    def require_api_token(authorization: str | None) -> None:
        """Protect stateful/LLM endpoints when deployed publicly.

        Local development remains frictionless when ``API_AUTH_TOKEN`` is not
        set.  Production deployment should always set it through a secret,
        never through the browser bundle or a committed file.
        """
        expected = os.getenv("API_AUTH_TOKEN")
        if not expected:
            if os.getenv("DEPLOYMENT_ENV", "local-research") != "local-research":
                raise HTTPException(status_code=503, detail="API authentication is not configured")
            return
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="Valid API bearer token required")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        storage = "dynamodb" if os.getenv("INVESTIGATION_DDB_TABLE") else "in_memory"
        return {
            "status": "ok",
            "mode": "deterministic",
            "deployment": os.getenv("DEPLOYMENT_ENV", "local-research"),
            "storage": storage,
        }

    @app.get("/api/datasets")
    def datasets() -> dict[str, list[dict[str, object]]]:
        return {"datasets": [app.state.repository.dataset_status(name) for name in DatasetName]}

    @app.get("/api/incidents")
    def incidents(dataset: DatasetName | None = None) -> dict[str, list[dict[str, object]]]:
        return {
            "incidents": [
                {
                    "id": item.id,
                    "source_dataset": item.source_dataset,
                    "title": item.title,
                    "time_range_s": item.time_range_s,
                    "capabilities": sorted(cap.value for cap in item.capabilities),
                }
                for item in app.state.repository.list_incidents(dataset)
            ]
        }

    @app.get("/api/incidents/{incident_id}")
    def incident_detail(incident_id: str) -> dict[str, object]:
        incident = app.state.repository.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return incident.model_dump(mode="json")

    @app.post("/api/incidents/{incident_id}/investigations")
    def create_investigation(
        incident_id: str,
        body: InvestigationRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        incident = app.state.repository.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        try:
            result = run_investigation(
                incident, body.diagnosis_time, body.question, body.include_llm_narrative
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        investigation_id = uuid.uuid4().hex
        app.state.investigations.save(investigation_id, result)
        return {"investigation_id": investigation_id, **result.model_dump(mode="json")}

    @app.get("/api/investigations/{investigation_id}")
    def get_investigation(
        investigation_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        result = app.state.investigations.get(investigation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        return {"investigation_id": investigation_id, **result.model_dump(mode="json")}

    @app.post("/api/investigations/{investigation_id}/reviews")
    def create_review(
        investigation_id: str,
        body: ReviewDecision,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        review = StoredReview(
            investigation_id=investigation_id,
            decision=body.decision,
            comment=body.comment,
            reviewer=body.reviewer,
            reviewed_at=datetime.now(UTC).isoformat(),
        )
        try:
            app.state.investigations.add_review(investigation_id, review)
        except InvestigationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Investigation not found") from exc
        return review.model_dump(mode="json")

    @app.get("/api/investigations/{investigation_id}/report")
    def get_report(
        investigation_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        result = app.state.investigations.get(investigation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        reviews = app.state.investigations.list_reviews(investigation_id)
        report = InvestigationReport(
            investigation_id=investigation_id,
            result=result,
            reviews=reviews,
        )
        return report.model_dump(mode="json")

    @app.post("/api/investigations/{investigation_id}/chat")
    def chat(
        investigation_id: str,
        body: ChatRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        result = app.state.investigations.get(investigation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        return answer_question(result, body.question).model_dump(mode="json")

    return app


app = create_app()
