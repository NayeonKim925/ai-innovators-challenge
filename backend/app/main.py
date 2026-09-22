"""HTTP boundary for the local research MVP."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .data.runtime_repository import JsonRuntimeRepository
from .domain import (
    ActorContext,
    ActorRole,
    AnalysisRunRequest,
    CaseChatRequest,
    CaseCreateRequest,
    CaseReviewDecision,
    ChatRequest,
    DatasetName,
    DetectionRequest,
    ExpertTaskResponse,
    HandoverAcceptanceRequest,
    HandoverChangeRequest,
    HandoverCheckRequest,
    HandoverPublishRequest,
    HypothesisAssessmentRequest,
    InvestigationReport,
    InvestigationRequest,
    LLMStatus,
    OpenItemRequest,
    OpenItemUpdateRequest,
    OperatorObservationRequest,
    ReviewDecision,
    ShiftWorkspaceFilter,
    StoredReview,
    StructuringProposalAcceptRequest,
    StructuringProposalDismissRequest,
    StructuringProposalRequest,
    StructuringProposalResponse,
)
from .llm.bedrock_client import llm_is_configured, llm_model_id, llm_provider, llm_timeout_s
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
from .repositories.structuring_proposals import (
    StructuringProposalRepository,
    build_structuring_proposal_repository,
)
from .services.case_chat import answer_case_question
from .services.cases import (
    CaseTransitionError,
    HandoverLintError,
    accept_handover,
    add_analysis_run,
    append_operator_observation,
    assess_hypothesis,
    build_resume,
    build_shift_workspace,
    check_handover,
    create_open_item,
    get_case,
    list_cases,
    open_case,
    publish_handover,
    request_handover_changes,
    respond_to_task,
    review_case,
    update_open_item,
)
from .services.context_structuring import (
    accept_structuring_proposal,
    build_structuring_proposals,
)
from .services.detection import run_auto_detection
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
    structuring_proposals: StructuringProposalRepository | None = None,
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
    # Proposals are intentionally non-authoritative. Only an explicit accept
    # transition can change the Case aggregate.
    app.state.structuring_proposals = (
        structuring_proposals or build_structuring_proposal_repository()
    )

    def resolve_actor_context(
        actor_id: str | None,
        actor_role: ActorRole | None,
        fallback_id: str,
    ) -> ActorContext:
        """Resolve trusted request context while preserving local-MVP compatibility.

        Production deployments require both headers in middleware. Local tests and
        the research UI can still exercise the domain contract without auth setup;
        those calls are explicitly marked as a local fallback in the event payload.
        """
        has_trusted_context = bool(actor_id and actor_role)
        return ActorContext(
            actor_id=actor_id or fallback_id,
            role=actor_role or "operator",
            source="trusted_header" if has_trusted_context else "local_fallback",
        )
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-Actor-Id", "X-Actor-Role"],
    )

    @app.middleware("http")
    async def require_actor_context(request, call_next):
        required = os.getenv("ACTOR_CONTEXT_REQUIRED", "false").lower() == "true"
        if required and (
            request.url.path.startswith("/api/cases")
            or request.url.path.endswith("/cases")
        ) and request.method == "POST":
            actor_header = os.getenv("ACTOR_ID_HEADER", "X-Actor-Id")
            role_header = os.getenv("ACTOR_ROLE_HEADER", "X-Actor-Role")
            if not request.headers.get(actor_header) or not request.headers.get(role_header):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Trusted actor context is required for Case writes"},
                )
        return await call_next(request)

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
        llm_configured = llm_is_configured()
        return {
            "status": "ok",
            "mode": "deterministic",
            "deployment": os.getenv("DEPLOYMENT_ENV", "local-research"),
            "storage": investigation_storage,
            "case_storage": case_storage,
            "llm_provider": llm_provider() if llm_configured else "not_configured",
            "llm_model": llm_model_id() if llm_configured else "",
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

    @app.post("/api/incidents/{incident_id}/detect")
    def detect_fault(
        incident_id: str,
        body: DetectionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Agent entry point: decide whether a fault has started, without a human cutoff.

        `body.observed_up_to_s` is the stream simulator's current playback position,
        not a cause-finding cutoff a human picked with foreknowledge of the answer
        (see docs/AGENT_FAULT_DETECTION_PLAN.md Phase 1). When the agent decides
        `trigger_rca`, this also runs and stores the RCA investigation automatically
        at the detected onset time -- the caller never chooses `diagnosis_time`.
        """
        require_api_token(authorization)
        incident = app.state.repository.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        if not incident.time_range_s.start <= body.observed_up_to_s <= incident.time_range_s.end:
            raise HTTPException(
                status_code=422,
                detail="observed_up_to_s must be within the runtime incident range",
            )
        detection, investigation = run_auto_detection(incident, body.observed_up_to_s)
        response: dict[str, object] = {"detection": detection.model_dump(mode="json")}
        if investigation is not None:
            investigation_id = uuid.uuid4().hex
            app.state.investigations.save(investigation_id, investigation)
            response["investigation_id"] = investigation_id
            response["investigation"] = investigation.model_dump(mode="json")
        else:
            response["investigation_id"] = None
            response["investigation"] = None
        return response

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

    @app.get("/api/shift-workspace")
    def shift_workspace(
        assignee: str | None = Query(default=None, max_length=120),
        status: ShiftWorkspaceFilter = Query(default="action_required"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        return build_shift_workspace(
            assignee=assignee,
            status=status,
            cases=app.state.cases,
        ).model_dump(mode="json")

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

    @app.post("/api/cases/{case_id}/structuring-proposals")
    def create_structuring_proposals(
        case_id: str,
        body: StructuringProposalRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Return reviewable note interpretations without changing the Case."""

        require_api_token(authorization)
        try:
            case = get_case(case_id, app.state.cases)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        if case.version != body.expected_version:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.")
        proposals = build_structuring_proposals(
            case=case,
            note=body.note,
            author=body.author,
            observed_at=body.observed_at,
            scope=body.scope,
            source_location=body.source_location,
            provenance=body.provenance,
            include_llm=body.include_llm,
        )
        for proposal in proposals:
            app.state.structuring_proposals.save(proposal)
        return StructuringProposalResponse(
            case_id=case.id,
            case_version=case.version,
            proposals=proposals,
        ).model_dump(mode="json")

    @app.get("/api/cases/{case_id}/structuring-proposals")
    def list_structuring_proposals(
        case_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Restore pending proposals without treating them as Case state."""

        require_api_token(authorization)
        try:
            case = get_case(case_id, app.state.cases)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        return StructuringProposalResponse(
            case_id=case.id,
            case_version=case.version,
            proposals=app.state.structuring_proposals.list_for_case(case.id),
        ).model_dump(mode="json")

    @app.post("/api/cases/{case_id}/structuring-proposals/{proposal_id}/accept")
    def accept_case_structuring_proposal(
        case_id: str,
        proposal_id: str,
        body: StructuringProposalAcceptRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Apply exactly one explicitly reviewed proposal to Case state."""

        require_api_token(authorization)
        proposal = app.state.structuring_proposals.get(proposal_id)
        if proposal is None or proposal.case_id != case_id:
            raise HTTPException(status_code=404, detail="Structuring proposal not found")
        try:
            case = get_case(case_id, app.state.cases)
            if case.version != body.expected_version or proposal.case_version != case.version:
                raise CaseConflictError(case_id)
            updated = accept_structuring_proposal(
                proposal=proposal,
                request=body,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        app.state.structuring_proposals.delete(proposal_id)
        return updated.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/structuring-proposals/{proposal_id}/dismiss")
    def dismiss_case_structuring_proposal(
        case_id: str,
        proposal_id: str,
        body: StructuringProposalDismissRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        """Remove a proposal from the review queue without mutating the Case."""

        require_api_token(authorization)
        proposal = app.state.structuring_proposals.get(proposal_id)
        if proposal is None or proposal.case_id != case_id:
            raise HTTPException(status_code=404, detail="Structuring proposal not found")
        app.state.structuring_proposals.delete(proposal_id)
        return {"proposal_id": proposal_id, "status": "dismissed"}

    @app.post("/api/cases/{case_id}/observations")
    def record_observation(
        case_id: str,
        body: OperatorObservationRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = append_operator_observation(
                case_id=case_id,
                original_text=body.original_text,
                author=body.author,
                observed_at=body.observed_at,
                scope=body.scope,
                source_location=body.source_location,
                provenance=body.provenance,
                is_current_state=body.is_current_state,
                expected_version=body.expected_version,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/analysis-runs")
    def create_analysis_run(
        case_id: str,
        body: AnalysisRunRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        current_case = app.state.cases.get(case_id)
        if current_case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        incident = app.state.repository.get_incident(current_case.incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        try:
            updated = add_analysis_run(
                case_id=case_id,
                incident=incident,
                diagnosis_time=body.diagnosis_time,
                question=body.question,
                created_by=body.created_by,
                idempotency_key=body.idempotency_key,
                expected_version=body.expected_version,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return updated.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/open-items")
    def create_case_open_item(
        case_id: str,
        body: OpenItemRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = create_open_item(
                case_id=case_id,
                title=body.title,
                requested_role=body.requested_role,
                assignee=body.assignee,
                due_at=body.due_at,
                run_id=body.run_id,
                evidence_ids=body.evidence_ids,
                expected_version=body.expected_version,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/open-items/{item_id}/updates")
    def update_case_open_item(
        case_id: str,
        item_id: str,
        body: OpenItemUpdateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = update_open_item(
                case_id=case_id,
                item_id=item_id,
                status=body.status,
                assignee=body.assignee,
                hold_reason=body.hold_reason,
                completion_note=body.completion_note,
                observation_ids=body.observation_ids,
                expected_version=body.expected_version,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/hypotheses/{hypothesis_id}/assessments")
    def assess_case_hypothesis(
        case_id: str,
        hypothesis_id: str,
        body: HypothesisAssessmentRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = assess_hypothesis(
                case_id=case_id,
                hypothesis_id=hypothesis_id,
                judgment=body.judgment,
                updated_by=body.updated_by,
                change_reason=body.change_reason,
                supporting_observation_ids=body.supporting_observation_ids,
                opposing_evidence_ids=body.opposing_evidence_ids,
                expected_version=body.expected_version,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.get("/api/cases/{case_id}/resume")
    def case_resume(
        case_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            return build_resume(case_id, app.state.cases)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc

    @app.post("/api/cases/{case_id}/chat")
    def case_chat(
        case_id: str,
        body: CaseChatRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        require_api_token(authorization)
        try:
            case = get_case(case_id, app.state.cases)
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        return answer_case_question(
            case=case,
            question=body.question,
            include_llm=body.include_llm,
            investigations=app.state.investigations,
        ).model_dump(mode="json")

    @app.post("/api/cases/{case_id}/handover-checks")
    def run_handover_check(
        case_id: str,
        body: HandoverCheckRequest,
        authorization: str | None = Header(default=None),
        actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        actor_role: ActorRole | None = Header(default=None, alias="X-Actor-Role"),
    ) -> dict[str, object]:
        require_api_token(authorization)
        actor = resolve_actor_context(actor_id, actor_role, body.sender)
        try:
            findings, linted_case = check_handover(
                case_id=case_id,
                expected_version=body.expected_version,
                sender=body.sender,
                receiver=body.receiver,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        return {
            "case": linted_case.model_dump(mode="json"),
            "case_id": case_id,
            "expected_version": body.expected_version,
            "findings": [item.model_dump(mode="json") for item in findings],
            "blocking": any(item.severity.value == "blocking" for item in findings),
        }

    @app.post("/api/cases/{case_id}/handovers")
    def publish_case_handover(
        case_id: str,
        body: HandoverPublishRequest,
        authorization: str | None = Header(default=None),
        actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        actor_role: ActorRole | None = Header(default=None, alias="X-Actor-Role"),
    ) -> dict[str, object]:
        require_api_token(authorization)
        actor = resolve_actor_context(actor_id, actor_role, body.sender)
        try:
            case = publish_handover(
                case_id=case_id,
                sender=body.sender,
                receiver=body.receiver,
                exception_reason=body.exception_reason,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                expected_version=body.expected_version,
                investigations=app.state.investigations,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except HandoverLintError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Handover has blocking findings",
                    "findings": [item.model_dump(mode="json") for item in exc.findings],
                },
            ) from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/handovers/{handover_id}/acceptance")
    def accept_case_handover(
        case_id: str,
        handover_id: str,
        body: HandoverAcceptanceRequest,
        authorization: str | None = Header(default=None),
        actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        actor_role: ActorRole | None = Header(default=None, alias="X-Actor-Role"),
    ) -> dict[str, object]:
        require_api_token(authorization)
        actor = resolve_actor_context(actor_id, actor_role, body.accepted_by)
        try:
            case = accept_handover(
                case_id=case_id,
                handover_id=handover_id,
                snapshot_id=body.snapshot_id,
                accepted_by=body.accepted_by,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                expected_version=body.expected_version,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/handovers/{handover_id}/change-requests")
    def change_case_handover(
        case_id: str,
        handover_id: str,
        body: HandoverChangeRequest,
        authorization: str | None = Header(default=None),
        actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
        actor_role: ActorRole | None = Header(default=None, alias="X-Actor-Role"),
    ) -> dict[str, object]:
        require_api_token(authorization)
        actor = resolve_actor_context(actor_id, actor_role, body.requested_by)
        try:
            case = request_handover_changes(
                case_id=case_id,
                handover_id=handover_id,
                requested_by=body.requested_by,
                reason=body.reason,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                expected_version=body.expected_version,
                cases=app.state.cases,
            )
        except CaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Case not found") from exc
        except CaseConflictError as exc:
            raise HTTPException(status_code=409, detail="Case changed. Refresh and retry.") from exc
        except CaseTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case.model_dump(mode="json")

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
