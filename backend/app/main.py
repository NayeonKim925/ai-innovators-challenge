"""HTTP boundary for the local research MVP."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data.runtime_repository import JsonRuntimeRepository
from .domain import DatasetName, InvestigationRequest
from .workflows.investigation import investigate


def create_app(repository: JsonRuntimeRepository | None = None) -> FastAPI:
    app = FastAPI(
        title="Manufacturing Investigation API",
        version="0.1.0",
        description="Local research MVP. It does not control manufacturing equipment.",
    )
    app.state.repository = repository or JsonRuntimeRepository()
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "deterministic", "deployment": "local-research"}

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
    def create_investigation(incident_id: str, body: InvestigationRequest) -> dict[str, object]:
        incident = app.state.repository.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        try:
            return investigate(incident, body.diagnosis_time, body.question).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
