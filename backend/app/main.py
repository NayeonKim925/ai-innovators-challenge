"""HTTP boundary for the local research MVP."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .data.runtime_repository import JsonRuntimeRepository
from .domain import (
    CaseCreateRequest,
    CaseReviewDecision,
    ChatRequest,
    DatasetName,
    ExpertTaskResponse,
    InvestigationReport,
    InvestigationRequest,
    LLMStatus,
    ReviewDecision,
    StoredReview,
)
from .llm.bedrock_client import bedrock_model_id, llm_timeout_s
from .repositories.cases import (
    CaseConflictError,
    CaseNotFoundError,
    CaseRepository,
    build_case_repository,
)
from .repositories.investigation_store import (
    InvestigationRepository,
    build_investigation_repository,
)
from .repositories.investigations import InvestigationNotFoundError
from .services.cases import (
    CaseTransitionError,
    get_case,
    list_cases,
    open_case,
    respond_to_task,
    review_case,
)
from .services.investigations import answer_question, run_investigation
from .services.narrative_jobs import (
    NarrativeQueueUnavailable,
    enqueue_narrative_job,
    mark_queued,
)


def create_app(
    repository: JsonRuntimeRepository | None = None,
    investigations: InvestigationRepository | None = None,
    cases: CaseRepository | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Manufacturing Investigation API",
        version="0.2.0",
        description=(
            "Evidence-linked incident investigation service. It does not control equipment."
        ),
    )
    app.state.repository = repository or JsonRuntimeRepository()
    app.state.investigations = investigations or build_investigation_repository()
    app.state.cases = cases or build_case_repository()
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
    def health() -> dict[str, object]:
        investigation_storage = (
            "dynamodb" if os.getenv("INVESTIGATION_DDB_TABLE") else "in_memory"
        )
        case_storage = "dynamodb" if os.getenv("CASE_DDB_TABLE") else "in_memory"
        guardrail_configured = bool(os.getenv("BEDROCK_GUARDRAIL_ID"))
        llm_configured = bool(os.getenv("BEDROCK_MODEL_ID"))
        return {
            "status": "ok",
            "mode": "deterministic",
            "deployment": os.getenv("DEPLOYMENT_ENV", "local-research"),
            "storage": investigation_storage,
            "case_storage": case_storage,
            "llm_provider": "bedrock" if llm_configured else "not_configured",
            "llm_model": bedrock_model_id() if llm_configured else "",
            "llm_timeout_s": llm_timeout_s(),
            "guardrail_configured": guardrail_configured,
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
        if body.async_llm_narrative and not body.include_llm_narrative:
            raise HTTPException(
                status_code=422,
                detail="async_llm_narrative requires include_llm_narrative=true",
            )
        try:
            result = run_investigation(
                incident,
                body.diagnosis_time,
                body.question,
                False if body.async_llm_narrative else body.include_llm_narrative,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        investigation_id = uuid.uuid4().hex
        app.state.investigations.save(investigation_id, result)
        if body.async_llm_narrative:
            if not any(candidate.status == "candidate" for candidate in result.candidates):
                skipped = run_investigation(
                    incident, body.diagnosis_time, body.question, True
                )
                app.state.investigations.replace(investigation_id, skipped)
                return {"investigation_id": investigation_id, **skipped.model_dump(mode="json")}
            queued = mark_queued(result)
            # Persist the queued state before publishing the message. A fast
            # worker may consume the message immediately after send_message.
            app.state.investigations.replace(investigation_id, queued)
            try:
                enqueue_narrative_job(investigation_id)
                result = queued
            except NarrativeQueueUnavailable as exc:
                failed = queued.model_copy(update={"llm_status": LLMStatus.UNAVAILABLE})
                app.state.investigations.replace(investigation_id, failed)
                detail = {
                    "message": (
                        "Deterministic investigation was saved, but the LLM job queue "
                        "is unavailable."
                    ),
                    "investigation_id": investigation_id,
                }
                raise HTTPException(status_code=503, detail=detail) from exc
            return JSONResponse(
                status_code=202,
                content={"investigation_id": investigation_id, **result.model_dump(mode="json")},
            )
        return {"investigation_id": investigation_id, **result.model_dump(mode="json")}

    @app.post("/api/incidents/{incident_id}/cases")
    def create_case(
        incident_id: str,
        body: CaseCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Open an evidence-closure case without calling an LLM.

        The deterministic investigation is stored separately and linked by
        ``investigation_id`` so a user can inspect the original candidates,
        evidence, and tool trace behind the follow-up task.
        """
        require_api_token(authorization)
        incident = app.state.repository.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        try:
            case = open_case(
                incident=incident,
                diagnosis_time=body.diagnosis_time,
                question=body.question,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.get("/api/cases")
    def cases(authorization: str | None = Header(default=None)) -> dict[str, object]:
        require_api_token(authorization)
        return {"cases": [item.model_dump(mode="json") for item in list_cases(app.state.cases)]}

    @app.get("/api/cases/{case_id}")
    def case_detail(
        case_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            return get_case(case_id, app.state.cases).model_dump(mode="json")
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc

    @app.post("/api/cases/{case_id}/tasks/{task_id}/responses")
    def record_evidence_response(
        case_id: str,
        task_id: str,
        body: ExpertTaskResponse,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = respond_to_task(
                case_id=case_id,
                task_id=task_id,
                response=body,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="Case changed while processing this response. Refresh and retry.",
            ) from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/reviews")
    def create_case_review(
        case_id: str,
        body: CaseReviewDecision,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = review_case(case_id=case_id, decision=body, cases=app.state.cases)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="Case changed while processing this review. Refresh and retry.",
            ) from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

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
