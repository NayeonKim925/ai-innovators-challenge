"""Deterministic continuity checks for a handover packet."""

from __future__ import annotations

from ..domain import (
    CaseStatus,
    HandoverFinding,
    HandoverFindingSeverity,
    InvestigationCase,
    OpenItemStatus,
)
from ..repositories.investigation_store import InvestigationRepository


def lint_case(
    case: InvestigationCase,
    investigations: InvestigationRepository | None = None,
) -> list[HandoverFinding]:
    """Return findings without changing Case state or calling an LLM.

    Unresolved work is intentionally a warning: a handover exists to transmit
    unfinished work. Missing ownership, current state, or run references are
    blocking because the receiver could not safely reconstruct the Case.
    """

    findings: list[HandoverFinding] = []
    known_observation_ids = {item.id for item in case.observations}
    run_ids = {run.id for run in case.analysis_runs}
    evidence_by_run: dict[str, set[str]] | None = None
    if investigations is not None:
        evidence_by_run = {
            run.id: (
                {evidence.id for evidence in result.evidence}
                if (result := investigations.get(run.investigation_id)) is not None
                else set()
            )
            for run in case.analysis_runs
        }

    def has_invalid_evidence(run_id: str | None, evidence_ids: list[str]) -> bool:
        if evidence_by_run is None:
            return False
        if run_id is None:
            # Compatibility for an in-memory legacy object. Persisted Cases are
            # backfilled with a Run by the repository reader.
            all_evidence = set().union(*evidence_by_run.values()) if evidence_by_run else set()
            return bool(set(evidence_ids) - all_evidence)
        if run_id not in run_ids:
            return True
        return bool(set(evidence_ids) - evidence_by_run.get(run_id, set()))

    for task in case.tasks:
        if task.run_id is not None and task.run_id not in run_ids:
            invalid_task_reference = True
        else:
            invalid_task_reference = has_invalid_evidence(task.run_id, task.evidence_ids)
        if invalid_task_reference:
            findings.append(
                HandoverFinding(
                    code="invalid-reference",
                    severity=HandoverFindingSeverity.BLOCKING,
                    message="Evidence Task가 해당 분석 Run에 없는 근거를 참조합니다.",
                    entity_id=task.id,
                )
            )
    for item in case.open_items:
        invalid_observations = set(item.observation_ids) - known_observation_ids
        invalid_evidence = has_invalid_evidence(item.run_id, item.evidence_ids)
        invalid_run = item.run_id is not None and item.run_id not in run_ids
        if invalid_observations or invalid_evidence or invalid_run:
            findings.append(
                HandoverFinding(
                    code="invalid-reference",
                    severity=HandoverFindingSeverity.BLOCKING,
                    message="Open Item이 현재 Case에 없는 관찰 또는 근거를 참조합니다.",
                    entity_id=item.id,
                )
            )
    for hypothesis in case.hypotheses:
        invalid_observations = set(hypothesis.supporting_observation_ids) - known_observation_ids
        invalid_evidence = has_invalid_evidence(
            hypothesis.run_id,
            [*hypothesis.evidence_ids, *hypothesis.opposing_evidence_ids],
        )
        invalid_run = hypothesis.run_id not in run_ids
        if invalid_observations or invalid_evidence or invalid_run:
            findings.append(
                HandoverFinding(
                    code="invalid-reference",
                    severity=HandoverFindingSeverity.BLOCKING,
                    message="가설이 현재 Case에 없는 관찰 또는 근거를 참조합니다.",
                    entity_id=hypothesis.id,
                )
            )
    if case.current_run_id is None or case.current_run_id not in run_ids:
        findings.append(
            HandoverFinding(
                code="missing-current-run",
                severity=HandoverFindingSeverity.BLOCKING,
                message="현재 분석 Run이 기록되지 않았습니다.",
                entity_id=case.current_run_id,
            )
        )

    if not any(
        observation.approved and observation.is_current_state
        for observation in case.observations
    ):
        findings.append(
            HandoverFinding(
                code="missing-current-state",
                severity=HandoverFindingSeverity.BLOCKING,
                message="현재 설비 상태임을 명시한 승인된 관찰 기록이 없습니다.",
            )
        )

    for item in case.open_items:
        if item.status is not OpenItemStatus.RESOLVED and not item.assignee:
            findings.append(
                HandoverFinding(
                    code="unassigned-open-item",
                    severity=HandoverFindingSeverity.BLOCKING,
                    message="열린 항목의 담당자가 지정되지 않았습니다.",
                    entity_id=item.id,
                )
            )
        if item.status is not OpenItemStatus.RESOLVED:
            findings.append(
                HandoverFinding(
                    code="unresolved-open-item",
                    severity=HandoverFindingSeverity.WARNING,
                    message="미확인 또는 미완료 항목을 인계 자료에 포함해야 합니다.",
                    entity_id=item.id,
                )
            )

    if case.status is CaseStatus.CLOSED and any(
        item.status is not OpenItemStatus.RESOLVED for item in case.open_items
    ):
        findings.append(
            HandoverFinding(
                code="closed-with-open-item",
                severity=HandoverFindingSeverity.BLOCKING,
                message="열린 항목이 남은 Case는 정상 종료 상태로 처리할 수 없습니다.",
            )
        )
    return findings


def has_blocking_findings(findings: list[HandoverFinding]) -> bool:
    return any(item.severity is HandoverFindingSeverity.BLOCKING for item in findings)
