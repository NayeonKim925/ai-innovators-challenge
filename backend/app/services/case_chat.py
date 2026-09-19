"""Case-aware Q&A with a deterministic Resume fallback."""

from __future__ import annotations

from ..domain import ChatResponse, InvestigationCase, InvestigationResult, LLMStatus, TraceEvent
from ..llm.explainer import generate_narrative
from ..repositories.investigation_store import InvestigationRepository


def _current_result(
    case: InvestigationCase, investigations: InvestigationRepository
) -> InvestigationResult | None:
    run = next((item for item in case.analysis_runs if item.id == case.current_run_id), None)
    if run is None:
        return None
    return investigations.get(run.investigation_id)


def _template_answer(
    case: InvestigationCase,
    result: InvestigationResult | None,
    question: str,
) -> tuple[str, list[str]]:
    evidence_ids = sorted(
        {
            evidence_id
            for candidate in (result.candidates if result is not None else [])
            for evidence_id in candidate.evidence_ids
            if result is not None
            and evidence_id in {evidence.id for evidence in result.evidence}
        }
    )
    observations = case.observations
    open_items = [item for item in case.open_items if item.status.value != "resolved"]
    lowered = question.lower()
    if any(token in lowered for token in ("남은", "미확인", "open", "남아")):
        if open_items:
            details = "; ".join(
                f"{item.title} ({item.status.value}, 담당: {item.assignee or '미지정'})"
                for item in open_items
            )
            return (
                f"현재 Case에서 남은 항목은 {details}입니다. "
                "미확인 상태는 원인 확정이나 수리 완료를 뜻하지 않습니다."
            ), evidence_ids
        return (
            "현재 기록된 미해결 Open Item은 없습니다. "
            "다만 이는 설비 수리 완료나 안전한 재가동을 의미하지 않습니다."
        ), evidence_ids
    if any(token in lowered for token in ("확인", "관찰", "기록", "무엇을")) and observations:
        details = "; ".join(
            f"{item.original_text} (작성자: {item.author})" for item in observations[-5:]
        )
        return (
            f"지금까지 기록된 관찰은 {details}입니다. "
            "원문과 출처 범위 안에서만 확인할 수 있습니다."
        ), evidence_ids
    if result is not None and result.candidates:
        candidates = ", ".join(
            f"{candidate.signal} (순위 {candidate.rank}, 근거 {', '.join(candidate.evidence_ids)})"
            for candidate in result.candidates
        )
        return (
            f"현재 분석 Run이 제시한 후보는 {candidates}입니다. "
            "이는 결정론적 분석의 조사 우선순위이며 확정 원인이 아닙니다. "
            "후보의 이유와 추가 판단은 인용된 근거와 사람의 확인 기록을 함께 검토해야 합니다."
        ), evidence_ids
    return (
        "현재 Case에서 근거 있는 후보를 확인할 수 없습니다. "
        "이유가 기록되지 않은 부분은 추정하지 않고, "
        "남은 Open Item과 원문 관찰을 먼저 확인해야 합니다."
    ), evidence_ids


def answer_case_question(
    *,
    case: InvestigationCase,
    question: str,
    include_llm: bool,
    investigations: InvestigationRepository,
) -> ChatResponse:
    result = _current_result(case, investigations)
    template, grounded_ids = _template_answer(case, result, question)
    trace = TraceEvent(
        step=6,
        tool="case_resume_template",
        detail=(
            "Answered from current Case state and stored runtime evidence; "
            "no new facts were inferred."
        ),
    )
    if not include_llm or result is None or not result.candidates:
        return ChatResponse(
            answer=template,
            grounded_evidence_ids=grounded_ids,
            llm_status=LLMStatus.NOT_REQUESTED if not include_llm else LLMStatus.SKIPPED,
            trace=trace,
        )

    contextual = result.model_copy(
        update={
            "question": (
                f"Case 현재 상태: {case.status.value}; "
                f"미해결 Open Item 수: "
                f"{len([item for item in case.open_items if item.status.value != 'resolved'])}. "
                f"사용자 질문: {question}"
            )
        }
    )
    narrative, llm_trace = generate_narrative(contextual)
    if narrative:
        return ChatResponse(
            answer=f"{template}\n\nAI 근거 정리:\n{narrative}",
            grounded_evidence_ids=grounded_ids,
            llm_status=LLMStatus.GENERATED,
            trace=llm_trace,
        )
    return ChatResponse(
        answer=template,
        grounded_evidence_ids=grounded_ids,
        blocked=llm_trace.tool == "bedrock_guardrail_blocked",
        llm_status={
            "bedrock_guardrail_blocked": LLMStatus.BLOCKED,
            "bedrock_narrative_unverified": LLMStatus.UNVERIFIED,
        }.get(llm_trace.tool, LLMStatus.UNAVAILABLE),
        trace=llm_trace,
    )
