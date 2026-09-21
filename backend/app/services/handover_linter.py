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
    known_evidence_ids: set[str] | None = None
    if investigations is not None:
        known_evidence_ids = {
            evidence.id
            for run in case.analysis_runs
            for result in [investigations.get(run.investigation_id)]
            if result is not None
            for evidence in result.evidence
        }
    for item in case.open_items:
        invalid_observations = set(item.observation_ids) - known_observation_ids
        invalid_evidence = (
            set(item.evidence_ids) - known_evidence_ids
            if known_evidence_ids is not None
            else set()
        )
        if invalid_observations or invalid_evidence:
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
        invalid_evidence = (
            (set(hypothesis.evidence_ids) | set(hypothesis.opposing_evidence_ids))
            - known_evidence_ids
            if known_evidence_ids is not None
            else set()
        )
        if invalid_observations or invalid_evidence:
            findings.append(
                HandoverFinding(
                    code="invalid-reference",
                    severity=HandoverFindingSeverity.BLOCKING,
                    message="가설이 현재 Case에 없는 관찰 또는 근거를 참조합니다.",
                    entity_id=hypothesis.id,
                )
            )
    run_ids = {run.id for run in case.analysis_runs}
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
