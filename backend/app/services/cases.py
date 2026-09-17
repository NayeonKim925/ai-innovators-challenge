"""Evidence-closure case orchestration.

This service deliberately has no LLM dependency. It turns an already grounded,
deterministic investigation into auditable human follow-up. A case can only be
closed after the requested evidence work and a separate expert review.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..domain import (
    CaseEvent,
    CaseReviewDecision,
    CaseStatus,
    EvidenceTask,
    EvidenceTaskStatus,
    ExpertResponseOutcome,
    ExpertTaskResponse,
    Incident,
    InvestigationCase,
    InvestigationResult,
    StoredCaseReview,
)
from ..repositories.cases import CaseNotFoundError, CaseRepository
from ..repositories.investigation_store import InvestigationRepository
from .investigations import run_investigation


class CaseTransitionError(ValueError):
    """Raised when a requested human action violates the case state contract."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _event(
    case: InvestigationCase,
    *,
    event_type: str,
    detail: str,
    actor: str,
    evidence_ids: list[str] | None = None,
    trace_steps: list[int] | None = None,
) -> CaseEvent:
    return CaseEvent(
        sequence=len(case.events) + 1,
        event_type=event_type,  # type: ignore[arg-type]
        detail=detail,
        actor=actor,  # type: ignore[arg-type]
        evidence_ids=evidence_ids or [],
        trace_steps=trace_steps or [],
        created_at=_now(),
    )


def _append_event(case: InvestigationCase, **kwargs: object) -> InvestigationCase:
    event = _event(case, **kwargs)  # type: ignore[arg-type]
    return case.model_copy(update={"events": [*case.events, event], "updated_at": event.created_at})


def _observation_task(case: InvestigationCase, created_at: str) -> EvidenceTask:
    return EvidenceTask(
        id=f"task_{uuid.uuid4().hex}",
        kind="collect_observation",
        requested_role="operator",
        title="추가 관측값을 기록해 주세요",
        instructions=(
            "현재 조사 범위에서는 근거가 충분한 원인 후보를 확정할 수 없습니다. "
            "선택한 진단 시점 전후에 관찰한 신호, 이벤트 또는 문서 위치를 기록해 주세요. "
            "이 응답은 새 조사 실행의 입력 검토용이며, 시스템이 원인을 자동 확정하지는 않습니다."
        ),
        trace_steps=[2, 3],
        created_at=created_at,
    )


def _first_task_for(
    result: InvestigationResult,
    case: InvestigationCase,
    created_at: str,
) -> EvidenceTask:
    candidate = next((item for item in result.candidates if item.status == "candidate"), None)
    if candidate is None:
        return _observation_task(case, created_at)
    return EvidenceTask(
        id=f"task_{uuid.uuid4().hex}",
        kind="verify_candidate",
        requested_role="process_expert",
        title=f"후보 신호 {candidate.signal}의 관측 근거를 확인해 주세요",
        instructions=(
            "아래 근거 ID가 가리키는 관측 신호와 사용 가능한 공정 문서를 비교해, "
            "이 후보를 추가 검토할 근거가 있는지만 응답해 주세요. 이는 실제 원인 확정이나 "
            "정비 지시가 아닙니다."
        ),
        candidate_signal=candidate.signal,
        evidence_ids=candidate.evidence_ids,
        trace_steps=[2, 3, 4],
        created_at=created_at,
    )


def open_case(
    *,
    incident: Incident,
    diagnosis_time: float,
    question: str,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> InvestigationCase:
    """Run deterministic analysis once, then plan one evidence-linked next action."""

    result = run_investigation(incident, diagnosis_time, question, include_llm_narrative=False)
    investigation_id = uuid.uuid4().hex
    investigations.save(investigation_id, result)
    created_at = _now()
    candidate_exists = any(item.status == "candidate" for item in result.candidates)
    case = InvestigationCase(
        id=f"case_{uuid.uuid4().hex}",
        incident_id=incident.id,
        dataset=incident.source_dataset,
        investigation_id=investigation_id,
        status=CaseStatus.AWAITING_EVIDENCE,
        next_action=(
            "Ask the assigned expert to verify the top evidence-linked candidate."
            if candidate_exists
            else "Collect additional observable context before opening a new investigation."
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    analysis_event = _event(
        case,
        event_type="analysis_completed",
        detail=(
            "Completed deterministic analysis and evidence validation; no LLM was used."
        ),
        actor="case_orchestrator",
        trace_steps=[event.step for event in result.trace],
    )
    case = case.model_copy(
        update={"events": [analysis_event], "updated_at": analysis_event.created_at}
    )
    task = _first_task_for(result, case, created_at)
    case = case.model_copy(update={"tasks": [task]})
    case = _append_event(
        case,
        event_type="evidence_task_created",
        detail=(
            f"Created {task.kind} task for {task.requested_role}; the case remains open "
            "until this evidence request is resolved."
        ),
        actor="case_orchestrator",
        evidence_ids=task.evidence_ids,
        trace_steps=task.trace_steps,
    )
    cases.save(case)
    return case


def list_cases(cases: CaseRepository) -> list[InvestigationCase]:
    return cases.list()


def get_case(case_id: str, cases: CaseRepository) -> InvestigationCase:
    case = cases.get(case_id)
    if case is None:
        raise CaseNotFoundError(case_id)
    return case


def _complete_task(
    case: InvestigationCase,
    task_id: str,
    response: ExpertTaskResponse,
) -> tuple[InvestigationCase, EvidenceTask]:
    task = next((item for item in case.tasks if item.id == task_id), None)
    if task is None:
        raise CaseTransitionError("Evidence task not found")
    if task.status is not EvidenceTaskStatus.PENDING:
        raise CaseTransitionError("Evidence task has already been completed")
    completed_at = _now()
    completed = task.model_copy(
        update={
            "status": EvidenceTaskStatus.COMPLETED,
            "response": response,
            "completed_at": completed_at,
        }
    )
    tasks = [completed if item.id == task_id else item for item in case.tasks]
    updated = case.model_copy(update={"tasks": tasks, "updated_at": completed_at})
    return updated, completed


def _add_observation_task(case: InvestigationCase) -> InvestigationCase:
    created_at = _now()
    task = _observation_task(case, created_at)
    updated = case.model_copy(update={"tasks": [*case.tasks, task], "updated_at": created_at})
    return _append_event(
        updated,
        event_type="evidence_task_created",
        detail=(
            "Created a follow-up observation task because the previous evidence check "
            "did not support a review-ready candidate."
        ),
        actor="case_orchestrator",
        trace_steps=task.trace_steps,
    )


def _persist_updated_case(
    *,
    current: InvestigationCase,
    updated: InvestigationCase,
    cases: CaseRepository,
) -> InvestigationCase:
    """Persist a transition only if no concurrent action changed the case."""

    persisted = updated.model_copy(update={"version": current.version + 1})
    cases.replace(persisted, expected_version=current.version)
    return persisted


def respond_to_task(
    *,
    case_id: str,
    task_id: str,
    response: ExpertTaskResponse,
    cases: CaseRepository,
) -> InvestigationCase:
    """Record an expert response and deterministically choose the next safe state."""

    case = get_case(case_id, cases)
    if case.status not in {CaseStatus.AWAITING_EVIDENCE, CaseStatus.REOPENED}:
        raise CaseTransitionError("This case is not awaiting an evidence response")
    updated, task = _complete_task(case, task_id, response)
    updated = _append_event(
        updated,
        event_type="expert_response_recorded",
        detail=(
            f"Recorded {response.outcome.value} response from {response.responder} for {task.kind}."
        ),
        actor="expert",
        evidence_ids=task.evidence_ids,
        trace_steps=task.trace_steps,
    )

    if task.kind == "verify_candidate" and response.outcome is ExpertResponseOutcome.CONFIRMED:
        updated = updated.model_copy(
            update={
                "status": CaseStatus.READY_FOR_REVIEW,
                "next_action": (
                    "An expert reviewer must explicitly approve or reject this "
                    "evidence-linked candidate."
                ),
            }
        )
        updated = _append_event(
            updated,
            event_type="case_ready_for_review",
            detail=(
                "Evidence verification is recorded. The candidate is review-ready, not an "
                "automatically confirmed root cause."
            ),
            actor="case_orchestrator",
            evidence_ids=task.evidence_ids,
        )
    elif task.kind == "verify_candidate":
        updated = updated.model_copy(
            update={
                "status": CaseStatus.REOPENED,
                "next_action": (
                    "Collect additional observable context, then open a new investigation "
                    "at an explicit cutoff."
                ),
            }
        )
        updated = _append_event(
            updated,
            event_type="case_reopened",
            detail=(
                "The candidate was not supported or could not be checked. The system did not "
                "infer an alternative cause."
            ),
            actor="case_orchestrator",
            evidence_ids=task.evidence_ids,
        )
        updated = _add_observation_task(updated)
    else:
        updated = updated.model_copy(
            update={
                "status": CaseStatus.ABSTAINED,
                "next_action": (
                    "No root-cause candidate is asserted. Reopen with newly observed "
                    "runtime data if available."
                ),
            }
        )
        updated = _append_event(
            updated,
            event_type="case_abstained",
            detail=(
                "Additional observation was recorded, but the existing result was not reranked "
                "and no root-cause candidate is asserted."
            ),
            actor="case_orchestrator",
            trace_steps=task.trace_steps,
        )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def review_case(
    *,
    case_id: str,
    decision: CaseReviewDecision,
    cases: CaseRepository,
) -> InvestigationCase:
    """Close only a review-ready case; rejection returns it to evidence collection."""

    case = get_case(case_id, cases)
    if case.status is not CaseStatus.READY_FOR_REVIEW:
        raise CaseTransitionError(
            "A case can only be reviewed after required evidence is confirmed."
        )
    review = StoredCaseReview(
        decision=decision.decision,
        comment=decision.comment,
        reviewer=decision.reviewer,
        reviewed_at=_now(),
    )
    updated = case.model_copy(
        update={"reviews": [*case.reviews, review], "updated_at": review.reviewed_at}
    )
    if decision.decision == "approve":
        updated = updated.model_copy(
            update={
                "status": CaseStatus.CLOSED,
                "next_action": (
                    "Case closed with an explicit expert review. The candidate remains "
                    "evidence-linked, not an automated control decision."
                ),
            }
        )
        updated = _append_event(
            updated,
            event_type="case_closed",
            detail="Closed after an explicit expert approval and completed evidence verification.",
            actor="expert",
        )
    else:
        updated = updated.model_copy(
            update={
                "status": CaseStatus.REOPENED,
                "next_action": (
                    "Collect additional observable context before opening a new investigation."
                ),
            }
        )
        updated = _append_event(
            updated,
            event_type="case_reopened",
            detail=(
                "Expert rejected the review-ready candidate; the case remains open for "
                "new evidence."
            ),
            actor="expert",
        )
        updated = _add_observation_task(updated)
    return _persist_updated_case(current=case, updated=updated, cases=cases)
