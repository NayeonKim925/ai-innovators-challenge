"""Orchestrates the deterministic workflow with the optional LLM narrative
step (ADR-0002 / M4 gate).

`workflows/investigation.py` stays purely deterministic (no LLM import, per
docs/ARCHITECTURE.md's "workflows: ... 수치 계산이나 장비 제어를 하지 않음").
This module is the one place that decides *whether* to also call
`llm.explainer.generate_narrative()` after the deterministic result exists,
and never before -- the LLM never sees a candidate list before evidence_check
has already run inside `investigate()`.
"""

from __future__ import annotations

from ..domain import ChatResponse, Incident, InvestigationResult, LLMStatus
from ..llm.explainer import generate_narrative
from ..workflows.investigation import investigate


def run_investigation(
    incident: Incident,
    diagnosis_time: float,
    question: str,
    include_llm_narrative: bool,
) -> InvestigationResult:
    """Runs the deterministic workflow first; it is always computed and never
    altered by the optional LLM step.

    If `include_llm_narrative` is False, or the LLM call fails/is unavailable,
    `mode` stays "deterministic" and `llm_narrative` stays None (ADR-0002) --
    callers can tell from the response alone whether the LLM actually ran, no
    other flag needed. A failed/skipped-vs-attempted LLM call still leaves a
    trace entry when attempted, for auditability.
    """
    result = investigate(incident, diagnosis_time, question)
    if not include_llm_narrative:
        return result
    if not any(candidate.status == "candidate" for candidate in result.candidates):
        from ..domain import TraceEvent

        return result.model_copy(
            update={
                "trace": [
                    *result.trace,
                    TraceEvent(
                        step=5,
                        tool="bedrock_llm_narrative_skipped",
                        detail="No verified candidate existed, so the LLM was not called.",
                    ),
                ],
                "llm_status": LLMStatus.SKIPPED,
            }
        )
    narrative, trace_event = generate_narrative(result)
    updates: dict[str, object] = {"trace": [*result.trace, trace_event]}
    if narrative is not None:
        updates["mode"] = "deterministic_with_llm_narrative"
        updates["llm_narrative"] = narrative
        updates["llm_status"] = LLMStatus.GENERATED
    else:
        updates["llm_status"] = {
            "bedrock_guardrail_blocked": LLMStatus.BLOCKED,
            "bedrock_narrative_unverified": LLMStatus.UNVERIFIED,
        }.get(trace_event.tool, LLMStatus.UNAVAILABLE)
    return result.model_copy(update=updates)


def answer_question(result: InvestigationResult, question: str) -> ChatResponse:
    """Answer a follow-up question using only the stored investigation context."""

    contextual = result.model_copy(update={"question": question})
    grounded_ids = [eid for candidate in result.candidates for eid in candidate.evidence_ids]
    if result.llm_status in {LLMStatus.QUEUED, LLMStatus.RUNNING}:
        return ChatResponse(
            answer=(
                "현재 결정론적 분석 결과는 준비되어 있지만 AI 요약을 생성하는 중입니다. "
                "아래 근거를 먼저 확인하고 잠시 후 다시 질문해 주세요."
            ),
            grounded_evidence_ids=grounded_ids,
            llm_status=result.llm_status,
        )
    if result.llm_status in {
        LLMStatus.BLOCKED,
        LLMStatus.UNAVAILABLE,
        LLMStatus.UNVERIFIED,
    }:
        signals = ", ".join(candidate.signal for candidate in result.candidates)
        return ChatResponse(
            answer=(
                f"현재 조사에서 확인된 후보는 {signals}입니다. "
                "이전 AI 요약이 안전 정책 또는 가용성 검사를 통과하지 못해 "
                "추가 호출은 생략합니다. 각 후보의 근거를 전문가가 확인하세요."
            ),
            grounded_evidence_ids=grounded_ids,
            blocked=result.llm_status == LLMStatus.BLOCKED,
            llm_status=result.llm_status,
            trace=result.trace[-1] if result.trace else None,
        )
    if not any(candidate.status == "candidate" for candidate in result.candidates):
        from ..domain import TraceEvent

        return ChatResponse(
            answer=(
                "현재 조사 결과에는 검증된 원인 후보가 없습니다. 질문에 답하려면 "
                "추가 관측값이나 해당 시점의 공정 기록이 필요합니다."
            ),
            trace=TraceEvent(
                step=5,
                tool="bedrock_llm_narrative_skipped",
                detail=(
                    "No verified candidate existed, so the chat request was answered "
                    "deterministically."
                ),
            ),
            llm_status=LLMStatus.SKIPPED,
        )
    narrative, trace_event = generate_narrative(contextual)
    if narrative:
        return ChatResponse(
            answer=narrative,
            grounded_evidence_ids=grounded_ids,
            llm_status=LLMStatus.GENERATED,
            trace=trace_event,
        )
    if not result.candidates:
        answer = (
            "현재 조사 결과에는 검증된 원인 후보가 없습니다. 질문에 답하려면 "
            "추가 관측값이나 해당 시점의 공정 기록이 필요합니다."
        )
    else:
        signals = ", ".join(candidate.signal for candidate in result.candidates)
        answer = (
            f"현재 조사에서 확인된 후보는 {signals}입니다. "
            "LLM 답변은 생성되지 않았으므로 각 후보의 근거와 실제 공정 기록을 전문가가 확인하세요."
        )
    return ChatResponse(
        answer=answer,
        grounded_evidence_ids=grounded_ids,
        blocked=trace_event.tool == "bedrock_guardrail_blocked",
        llm_status={
            "bedrock_guardrail_blocked": LLMStatus.BLOCKED,
            "bedrock_narrative_unverified": LLMStatus.UNVERIFIED,
        }.get(trace_event.tool, LLMStatus.UNAVAILABLE),
        trace=trace_event,
    )
