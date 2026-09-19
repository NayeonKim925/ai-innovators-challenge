"""Evidence-closure case orchestration.

This service deliberately has no LLM dependency. It turns an already grounded,
deterministic investigation into auditable human follow-up. A case can only be
closed after the requested evidence work and a separate expert review.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from ..domain import (
    AnalysisRun,
    CaseEvent,
    CaseReviewDecision,
    CaseStatus,
    EvidenceTask,
    EvidenceTaskStatus,
    ExpertResponseOutcome,
    ExpertTaskResponse,
    Handover,
    HandoverFinding,
    HandoverSnapshot,
    HandoverStatus,
    HypothesisJudgment,
    HypothesisTrack,
    Incident,
    InvestigationCase,
    InvestigationResult,
    OpenItem,
    OpenItemStatus,
    OperatorObservation,
    StoredCaseReview,
)
from ..repositories.cases import CaseConflictError, CaseNotFoundError, CaseRepository
from ..repositories.investigation_store import InvestigationRepository
from .handover_linter import has_blocking_findings, lint_case
from .investigations import run_investigation


class CaseTransitionError(ValueError):
    """Raised when a requested human action violates the case state contract."""


class HandoverLintError(CaseTransitionError):
    """Raised when blocking deterministic findings prevent publication."""

    def __init__(self, findings: list[HandoverFinding]) -> None:
        self.findings = findings
        super().__init__("Handover has blocking findings")


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


def _open_item_for_task(task: EvidenceTask, created_at: str) -> OpenItem:
    return OpenItem(
        id=f"item_{uuid.uuid4().hex}",
        title=task.title,
        requested_role=task.requested_role,
        status=OpenItemStatus.NOT_STARTED,
        evidence_ids=task.evidence_ids,
        created_at=created_at,
        updated_at=created_at,
    )


def _hypotheses_for_result(
    result: InvestigationResult, run_id: str, updated_at: str
) -> list[HypothesisTrack]:
    return [
        HypothesisTrack(
            id=f"hyp_{uuid.uuid4().hex}",
            run_id=run_id,
            candidate_signal=candidate.signal,
            evidence_ids=candidate.evidence_ids,
            updated_at=updated_at,
        )
        for candidate in result.candidates
        if candidate.status == "candidate"
    ]


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
    run = AnalysisRun(
        id=f"run_{uuid.uuid4().hex}",
        investigation_id=investigation_id,
        incident_id=incident.id,
        dataset=incident.source_dataset,
        diagnosis_time=diagnosis_time,
        algorithm_version="deterministic-investigation-v1",
        created_by="case_orchestrator",
        created_at=created_at,
    )
    candidate_exists = any(item.status == "candidate" for item in result.candidates)
    case = InvestigationCase(
        id=f"case_{uuid.uuid4().hex}",
        incident_id=incident.id,
        dataset=incident.source_dataset,
        investigation_id=investigation_id,
        status=CaseStatus.AWAITING_EVIDENCE,
        current_run_id=run.id,
        analysis_runs=[run],
        hypotheses=_hypotheses_for_result(result, run.id, created_at),
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
    item = _open_item_for_task(task, created_at)
    task = task.model_copy(update={"open_item_id": item.id})
    case = case.model_copy(update={"tasks": [task], "open_items": [item]})
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


def _update_item_from_task(
    case: InvestigationCase,
    task: EvidenceTask,
    response: ExpertTaskResponse,
) -> InvestigationCase:
    if task.open_item_id is None:
        return case
    item = next((item for item in case.open_items if item.id == task.open_item_id), None)
    if item is None:
        return case
    status = (
        OpenItemStatus.UNAVAILABLE
        if response.outcome is ExpertResponseOutcome.UNAVAILABLE
        else OpenItemStatus.NOT_RECORDED
        if task.kind == "collect_observation"
        else OpenItemStatus.RESOLVED
    )
    updated_item = item.model_copy(
        update={
            "status": status,
            "completion_note": response.comment,
            "updated_at": _now(),
        }
    )
    return case.model_copy(
        update={
            "open_items": [
                updated_item if current.id == updated_item.id else current
                for current in case.open_items
            ],
            "updated_at": updated_item.updated_at,
        }
    )


def _add_observation_task(case: InvestigationCase) -> InvestigationCase:
    created_at = _now()
    task = _observation_task(case, created_at)
    item = _open_item_for_task(task, created_at)
    task = task.model_copy(update={"open_item_id": item.id})
    updated = case.model_copy(
        update={
            "tasks": [*case.tasks, task],
            "open_items": [*case.open_items, item],
            "updated_at": created_at,
        }
    )
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
    if response.expected_version is not None and response.expected_version != case.version:
        raise CaseConflictError(case_id)
    if case.status not in {CaseStatus.AWAITING_EVIDENCE, CaseStatus.REOPENED}:
        raise CaseTransitionError("This case is not awaiting an evidence response")
    updated, task = _complete_task(case, task_id, response)
    updated = _update_item_from_task(updated, task, response)
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


def append_operator_observation(
    *,
    case_id: str,
    original_text: str,
    author: str,
    observed_at: str | None,
    scope: str,
    source_location: str,
    provenance: str,
    expected_version: int,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    recorded_at = _now()
    observation = OperatorObservation(
        id=f"obs_{uuid.uuid4().hex}",
        original_text=original_text,
        author=author,
        observed_at=observed_at,
        recorded_at=recorded_at,
        scope=scope,
        source_location=source_location,
        provenance=provenance,
        approved=True,
    )
    updated = case.model_copy(
        update={
            "observations": [*case.observations, observation],
            "next_action": (
                "Review the new observation and decide whether a new analysis Run is needed."
            ),
            "updated_at": recorded_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="observation_recorded",
        detail=(
            f"Recorded operator observation {observation.id}; "
            "it is not a machine sensor reading."
        ),
        actor="operator",
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def add_analysis_run(
    *,
    case_id: str,
    incident: Incident,
    diagnosis_time: float,
    question: str,
    created_by: str,
    expected_version: int,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    if case.status is CaseStatus.CLOSED:
        raise CaseTransitionError("A closed case cannot receive a new analysis run")
    result = run_investigation(incident, diagnosis_time, question, include_llm_narrative=False)
    investigation_id = uuid.uuid4().hex
    investigations.save(investigation_id, result)
    created_at = _now()
    run = AnalysisRun(
        id=f"run_{uuid.uuid4().hex}",
        investigation_id=investigation_id,
        incident_id=incident.id,
        dataset=incident.source_dataset,
        diagnosis_time=diagnosis_time,
        algorithm_version="deterministic-investigation-v1",
        created_by=created_by,
        created_at=created_at,
    )
    task = _first_task_for(result, case, created_at)
    item = _open_item_for_task(task, created_at)
    task = task.model_copy(update={"open_item_id": item.id})
    updated = case.model_copy(
        update={
            "current_run_id": run.id,
            "analysis_runs": [*case.analysis_runs, run],
            "hypotheses": [
                *case.hypotheses,
                *_hypotheses_for_result(result, run.id, created_at),
            ],
            "tasks": [*case.tasks, task],
            "open_items": [*case.open_items, item],
            "status": CaseStatus.AWAITING_EVIDENCE,
            "next_action": "Review the latest analysis Run and resolve its linked Open Item.",
            "updated_at": created_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="analysis_run_added",
        detail=(
            f"Added immutable deterministic analysis Run {run.id}; "
            "previous Runs were preserved."
        ),
        actor="analyst",
        trace_steps=[event.step for event in result.trace],
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def create_open_item(
    *,
    case_id: str,
    title: str,
    requested_role: str,
    assignee: str | None,
    due_at: str | None,
    evidence_ids: list[str],
    expected_version: int,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    known_evidence = {
        evidence.id
        for run in case.analysis_runs
        for result in [investigations.get(run.investigation_id)]
        if result is not None
        for evidence in result.evidence
    }
    if any(evidence_id not in known_evidence for evidence_id in evidence_ids):
        raise CaseTransitionError("Open item references unknown evidence")
    item = OpenItem(
        id=f"item_{uuid.uuid4().hex}",
        title=title,
        requested_role=requested_role,  # type: ignore[arg-type]
        assignee=assignee,
        due_at=due_at,
        evidence_ids=evidence_ids,
        created_at=_now(),
        updated_at=_now(),
    )
    updated = case.model_copy(
        update={"open_items": [*case.open_items, item], "updated_at": item.updated_at}
    )
    updated = _append_event(
        updated,
        event_type="open_item_updated",
        detail=f"Created Open Item {item.id} for {item.requested_role}.",
        actor="operator",
        evidence_ids=item.evidence_ids,
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def update_open_item(
    *,
    case_id: str,
    item_id: str,
    status: OpenItemStatus,
    assignee: str | None,
    hold_reason: str,
    completion_note: str,
    observation_ids: list[str],
    expected_version: int,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    item = next((item for item in case.open_items if item.id == item_id), None)
    if item is None:
        raise CaseTransitionError("Open item not found")
    if status is OpenItemStatus.RESOLVED and not completion_note.strip() and not observation_ids:
        raise CaseTransitionError("Resolved open item requires a completion note or observation")
    known_observations = {observation.id for observation in case.observations}
    if any(observation_id not in known_observations for observation_id in observation_ids):
        raise CaseTransitionError("Open item references an unknown observation")
    updated_at = _now()
    changed = item.model_copy(
        update={
            "status": status,
            "assignee": assignee,
            "hold_reason": hold_reason,
            "completion_note": completion_note,
            "observation_ids": observation_ids,
            "updated_at": updated_at,
        }
    )
    updated = case.model_copy(
        update={
            "open_items": [
                changed if current.id == item_id else current
                for current in case.open_items
            ],
            "updated_at": updated_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="open_item_updated",
        detail=f"Updated Open Item {item_id} to {status.value}.",
        actor="operator",
        evidence_ids=changed.evidence_ids,
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def assess_hypothesis(
    *,
    case_id: str,
    hypothesis_id: str,
    judgment: HypothesisJudgment,
    updated_by: str,
    change_reason: str,
    supporting_observation_ids: list[str],
    opposing_evidence_ids: list[str],
    expected_version: int,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    hypothesis = next((item for item in case.hypotheses if item.id == hypothesis_id), None)
    if hypothesis is None:
        raise CaseTransitionError("Hypothesis track not found")
    known_observations = {observation.id for observation in case.observations}
    known_evidence = {
        evidence.id
        for run in case.analysis_runs
        for result in [investigations.get(run.investigation_id)]
        if result is not None
        for evidence in result.evidence
    }
    if any(evidence_id not in known_evidence for evidence_id in opposing_evidence_ids):
        raise CaseTransitionError("Hypothesis references unknown evidence")
    if any(item_id not in known_observations for item_id in supporting_observation_ids):
        raise CaseTransitionError("Hypothesis references an unknown observation")
    updated_at = _now()
    changed = hypothesis.model_copy(
        update={
            "judgment": judgment,
            "updated_by": updated_by,
            "change_reason": change_reason,
            "supporting_observation_ids": supporting_observation_ids,
            "opposing_evidence_ids": opposing_evidence_ids,
            "updated_at": updated_at,
        }
    )
    updated = case.model_copy(
        update={
            "hypotheses": [
                changed if current.id == hypothesis_id else current
                for current in case.hypotheses
            ],
            "updated_at": updated_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="hypothesis_assessed",
        detail=(
            f"Recorded human assessment {judgment.value} for candidate "
            f"{hypothesis.candidate_signal}; this is not cause confirmation."
        ),
        actor="expert",
        evidence_ids=changed.evidence_ids,
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def _build_handover_snapshot(
    case: InvestigationCase,
    findings: list[HandoverFinding],
) -> HandoverSnapshot:
    payload = {
        "case_id": case.id,
        "source_case_version": case.version,
        "current_run_id": case.current_run_id,
        "current_run": next(
            (
                run.model_dump(mode="json")
                for run in case.analysis_runs
                if run.id == case.current_run_id
            ),
            None,
        ),
        "hypotheses": [item.model_dump(mode="json") for item in case.hypotheses],
        "open_items": [item.model_dump(mode="json") for item in case.open_items],
        "observations": [item.model_dump(mode="json") for item in case.observations],
        "constraints": [case.next_action],
    }
    evidence_ids = sorted({
        evidence_id
        for hypothesis in case.hypotheses
        for evidence_id in hypothesis.evidence_ids
    })
    snapshot_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return HandoverSnapshot(
        id=f"snapshot_{uuid.uuid4().hex}",
        case_id=case.id,
        source_case_version=case.version,
        snapshot_hash=snapshot_hash,
        current_run_id=case.current_run_id,
        hypothesis_ids=[item.id for item in case.hypotheses],
        evidence_ids=evidence_ids,
        open_item_ids=[item.id for item in case.open_items],
        observation_ids=[item.id for item in case.observations],
        constraints=[case.next_action],
        payload=payload,
        findings=findings,
        created_at=_now(),
    )


def check_handover(
    *,
    case_id: str,
    expected_version: int,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> list[HandoverFinding]:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    return lint_case(case, investigations)


def publish_handover(
    *,
    case_id: str,
    sender: str,
    receiver: str,
    exception_reason: str,
    expected_version: int,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    findings = lint_case(case, investigations)
    if has_blocking_findings(findings) and not exception_reason.strip():
        raise HandoverLintError(findings)
    snapshot = _build_handover_snapshot(case, findings)
    published_at = _now()
    handover = Handover(
        id=f"handover_{uuid.uuid4().hex}",
        sender=sender,
        receiver=receiver,
        # The packet represents the pre-publication Case state.
        source_case_version=case.version,
        snapshot_id=snapshot.id,
        exception_reason=exception_reason,
        created_at=published_at,
        published_at=published_at,
    )
    updated = case.model_copy(
        update={
            "handover_snapshots": [*case.handover_snapshots, snapshot],
            "handovers": [*case.handovers, handover],
            "current_handover_id": handover.id,
            "next_action": (
                "The receiver must review the handover Snapshot and accept or request changes."
            ),
            "updated_at": published_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="handover_published",
        detail=(
            f"Published handover {handover.id} from {sender} to {receiver}; "
            f"Snapshot {snapshot.id} is fixed to Case version {handover.source_case_version}."
        ),
        actor="operator",
    )
    if exception_reason.strip():
        updated = _append_event(
            updated,
            event_type="handover_linted",
            detail=f"Published with an explicit exception: {exception_reason}",
            actor="operator",
        )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def accept_handover(
    *,
    case_id: str,
    handover_id: str,
    snapshot_id: str,
    accepted_by: str,
    expected_version: int,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    handover = next((item for item in case.handovers if item.id == handover_id), None)
    if handover is None:
        raise CaseTransitionError("Handover not found")
    if handover.snapshot_id != snapshot_id:
        raise CaseTransitionError("Snapshot ID does not match the published handover")
    if handover.status is not HandoverStatus.PUBLISHED:
        raise CaseTransitionError("Only a published handover can be accepted")
    if handover.source_case_version + 1 != case.version:
        superseded = handover.model_copy(update={"status": HandoverStatus.SUPERSEDED})
        updated = case.model_copy(
            update={
                "handovers": [
                    superseded if item.id == handover_id else item
                    for item in case.handovers
                ],
                "updated_at": _now(),
            }
        )
        updated = _append_event(
            updated,
            event_type="handover_superseded",
            detail="The published Snapshot is stale because the Case changed after publication.",
            actor="system",
        )
        _persist_updated_case(current=case, updated=updated, cases=cases)
        raise CaseTransitionError("Published Snapshot is stale and must be reviewed again")
    accepted_at = _now()
    accepted = handover.model_copy(
        update={
            "status": HandoverStatus.ACCEPTED,
            "accepted_at": accepted_at,
            "accepted_by": accepted_by,
        }
    )
    updated = case.model_copy(
        update={
            "handovers": [accepted if item.id == handover_id else item for item in case.handovers],
            "next_action": case.next_action,
            "updated_at": accepted_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="handover_accepted",
        detail=(
            f"Receiver {accepted_by} accepted handover {handover_id}; "
            "Case investigation remains independent from handover acceptance."
        ),
        actor="operator",
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def request_handover_changes(
    *,
    case_id: str,
    handover_id: str,
    requested_by: str,
    reason: str,
    expected_version: int,
    cases: CaseRepository,
) -> InvestigationCase:
    case = get_case(case_id, cases)
    if case.version != expected_version:
        raise CaseConflictError(case_id)
    handover = next((item for item in case.handovers if item.id == handover_id), None)
    if handover is None:
        raise CaseTransitionError("Handover not found")
    if handover.status is not HandoverStatus.PUBLISHED:
        raise CaseTransitionError("Only a published handover can receive change requests")
    changed_at = _now()
    changed = handover.model_copy(
        update={
            "status": HandoverStatus.CHANGES_REQUESTED,
            "change_request": reason,
            "change_requested_at": changed_at,
        }
    )
    updated = case.model_copy(
        update={
            "handovers": [changed if item.id == handover_id else item for item in case.handovers],
            "updated_at": changed_at,
        }
    )
    updated = _append_event(
        updated,
        event_type="handover_changes_requested",
        detail=f"{requested_by} requested changes to handover {handover_id}: {reason}",
        actor="operator",
    )
    return _persist_updated_case(current=case, updated=updated, cases=cases)


def build_resume(case_id: str, cases: CaseRepository) -> dict[str, object]:
    case = get_case(case_id, cases)
    current_run = next(
        (run for run in case.analysis_runs if run.id == case.current_run_id), None
    )
    current_handover = next(
        (item for item in case.handovers if item.id == case.current_handover_id), None
    )
    snapshot = next(
        (
            item
            for item in case.handover_snapshots
            if current_handover is not None and item.id == current_handover.snapshot_id
        ),
        None,
    )
    return {
        "case_id": case.id,
        "case_version": case.version,
        "status": case.status.value,
        "next_action": case.next_action,
        "current_run": current_run.model_dump(mode="json") if current_run else None,
        "observations": [
            {
                "id": item.id,
                "text": item.original_text,
                "author": item.author,
                "recorded_at": item.recorded_at,
                "provenance": item.provenance.value,
            }
            for item in case.observations
        ],
        "open_items": [item.model_dump(mode="json") for item in case.open_items],
        "hypotheses": [item.model_dump(mode="json") for item in case.hypotheses],
        "current_handover": current_handover.model_dump(mode="json")
        if current_handover
        else None,
        "current_snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        "constraints": [case.next_action],
    }


def review_case(
    *,
    case_id: str,
    decision: CaseReviewDecision,
    cases: CaseRepository,
) -> InvestigationCase:
    """Close only a review-ready case; rejection returns it to evidence collection."""

    case = get_case(case_id, cases)
    if decision.expected_version is not None and decision.expected_version != case.version:
        raise CaseConflictError(case_id)
    if case.status is not CaseStatus.READY_FOR_REVIEW:
        raise CaseTransitionError(
            "A case can only be reviewed after required evidence is confirmed."
        )
    unresolved_items = [
        item for item in case.open_items if item.status is not OpenItemStatus.RESOLVED
    ]
    if unresolved_items:
        raise CaseTransitionError(
            "A case cannot close while required Open Items remain unresolved."
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
