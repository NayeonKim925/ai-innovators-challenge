"""LLM narrative generation — summarizes an already-computed InvestigationResult.

★ 이식 근거 (ADR-0002, 루트 agent.py에서 이식) ★
루트의 `agent.py`는 도구 호출 루프(get_root_cause_ranking, get_fault_reference)를
직접 짜서 최종 마크다운 보고서까지 만들었다. 이 backend 버전은 그 로직을
재사용하되, 이미 결정론적으로 계산된 `InvestigationResult`(candidates/evidence)를
입력으로 받는 것으로 축소한다 -- LLM이 이 함수 안에서 원인후보를 다시 계산할
방법이 없다. `summarize_candidates()`/`get_fault_reference()`(tools.py)가 반환한
값만 프롬프트에 들어간다.

★ AGENTS.md 원칙의 코드 강제 ★
- "수치는 도구가 계산한다": 여기서는 candidate.rank/reason/evidence를 그대로
  프롬프트에 넣고, LLM에게 순위를 매기라고 요청하지 않는다.
- "근거 없으면 판단 보류": `investigate()`가 이미 `evidence_check`로
  inconclusive를 걸러낸 뒤의 결과만 여기 들어온다. status="inconclusive"인
  candidate는 요약에서 "불확실"로 명시한다.
- Bedrock/anthropic SDK가 없거나 호출이 실패하면 `generate_narrative()`는
  `None`을 반환한다 -- 예외를 삼키고 결정론적 모드로 조용히 폴백한다.
"""

from __future__ import annotations

import logging
import time

from ..domain import InvestigationResult, TraceEvent
from .bedrock_client import (
    BedrockUnavailable,
    GuardrailBlocked,
    apply_guardrail,
    build_client,
    llm_model_id,
    llm_provider,
)
from .tools import get_fault_reference, summarize_candidates

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 반도체/제조 설비 이상 알람을 조사하는 보조 엔지니어입니다.

역할:
- 이미 결정론적 분석 도구가 계산한 원인후보와 근거를 받아, 사람이 읽기 좋은
  문장으로 정리합니다.
- 절대로 새로운 원인후보를 만들거나 순위를 바꾸지 마세요. 입력에 없는 수치를
  지어내지 마세요.

절대 지켜야 할 것:
- 원인을 "확정"하지 마세요. 항상 "가능성이 높은 후보"로 표현하고, 최종 판단은
  담당 엔지니어의 몫이라고 명시하세요.
- status가 "inconclusive"인 후보는 근거가 불충분하다는 사실을 그대로 밝히세요.
- 참고 배경지식은 AI가 정리한 일반 지식이며 검증된 매뉴얼이 아니라고 명시하세요.
- 사용자의 질문이 있으면 입력된 후보와 근거 범위 안에서만 답하고, 데이터가 부족하면
  추가로 확인해야 할 관측값을 제안하세요. 설비를 조작하는 명령은 만들지 마세요.
- 답변에서 사용하는 근거는 반드시 입력된 `E...` 근거 ID를 대괄호로 표시하세요.
- 2~4문단의 짧은 한국어 답변으로 작성하세요. 표나 긴 목록은 만들지 마세요.
"""


def _build_prompt(result: InvestigationResult) -> str:
    summary = summarize_candidates(result.candidates, result.evidence)
    lines = [
        f"사건 ID: {result.incident_id} (데이터셋: {result.dataset.value})",
        f"진단 시점(cutoff): {result.diagnosis_time}",
        f"사용자 질문: {result.question or '(질문 없음)'}",
        "",
        "결정론적 분석 결과(순위/근거는 이미 계산됨, 절대 바꾸지 말 것):",
    ]
    for candidate in summary["candidates"]:
        lines.append(
            f"- 순위 {candidate['rank']}: {candidate['signal']} "
            f"(status={candidate['status']}) — {candidate['reason']}"
        )
        for evidence in candidate["evidence"]:
            lines.append(
                f"  근거 {evidence['id']}: {evidence['title']} | {evidence['detail']} | 출처={evidence['source']}"
            )
        reference = get_fault_reference(candidate["signal"])
        if reference.get("found"):
            lines.append(
                f"  참고 배경지식(권위 문서 아님): {reference['role']} "
                f"(흔한 원인: {reference['common_causes']})"
            )
    if not result.candidates:
        lines.append("(원인후보가 산출되지 않았습니다. 판단 보류 상태입니다.)")
    return "\n".join(lines)


def _create_response(client: object, prompt: str) -> object:
    """Call the active provider without leaking provider details elsewhere."""
    if llm_provider() == "competition_gateway":
        return client.chat.completions.create(  # type: ignore[attr-defined]
            model=llm_model_id(),
            max_tokens=800,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    return client.messages.create(  # type: ignore[attr-defined]
        model=llm_model_id(),
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )


def _response_text(response: object) -> str:
    if llm_provider() == "competition_gateway":
        message = response.choices[0].message  # type: ignore[attr-defined]
        return message.content or ""
    return "".join(block.text for block in response.content if block.type == "text")  # type: ignore[attr-defined]


def _response_token_usage(response: object) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if llm_provider() == "competition_gateway":
        prompt_tokens = getattr(usage, "prompt_tokens", 0)
        completion_tokens = getattr(usage, "completion_tokens", 0)
    else:
        prompt_tokens = getattr(usage, "input_tokens", 0)
        completion_tokens = getattr(usage, "output_tokens", 0)
    return prompt_tokens + completion_tokens


def generate_narrative(result: InvestigationResult) -> tuple[str | None, TraceEvent]:
    """Bedrock Claude로 `result`를 요약한다. 실패하면 (None, trace_event)를
    반환하고, 성공하면 (narrative_text, trace_event)를 반환한다. 어느 쪽이든
    latency_ms는 실제로 측정된 값으로 채운다."""
    started = time.monotonic()
    try:
        prompt = _build_prompt(result)
        apply_guardrail(prompt, "INPUT")
        client = build_client()
        response = _create_response(client, prompt)
        narrative = _response_text(response)
        apply_guardrail(narrative, "OUTPUT")
        evidence_ids = {
            evidence_id for candidate in result.candidates for evidence_id in candidate.evidence_ids
        }
        if evidence_ids and not any(f"[{evidence_id}]" in narrative for evidence_id in evidence_ids):
            return None, TraceEvent(
                step=5,
                tool="bedrock_narrative_unverified",
                detail="The LLM response did not cite a verified evidence ID; deterministic output was preserved.",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                token_usage=None,
            )
        latency_ms = (time.monotonic() - started) * 1000
        token_usage = _response_token_usage(response)
        return narrative, TraceEvent(
            step=5,
            tool="bedrock_llm_narrative",
            detail=(
                f"Generated a narrative summary via {llm_provider()} / {llm_model_id()}. "
                "No candidates or scores were altered."
            ),
            latency_ms=round(latency_ms, 1),
            token_usage=token_usage,
        )
    except GuardrailBlocked:
        latency_ms = (time.monotonic() - started) * 1000
        return None, TraceEvent(
            step=5,
            tool="bedrock_guardrail_blocked",
            detail="The configured Guardrail blocked the narrative request or response.",
            latency_ms=round(latency_ms, 1),
            token_usage=None,
        )
    except BedrockUnavailable:
        LOGGER.warning("Bedrock narrative unavailable", exc_info=True)
        latency_ms = (time.monotonic() - started) * 1000
        return None, TraceEvent(
            step=5,
            tool="bedrock_llm_narrative",
            detail="LLM narrative unavailable; deterministic result was preserved.",
            latency_ms=round(latency_ms, 1),
            token_usage=None,
        )
    except Exception as exc:  # Never let an LLM failure break the request.
        LOGGER.exception("Unexpected Bedrock narrative failure: %s", type(exc).__name__)
        latency_ms = (time.monotonic() - started) * 1000
        return None, TraceEvent(
            step=5,
            tool="bedrock_llm_narrative",
            detail="LLM call failed; deterministic result was preserved.",
            latency_ms=round(latency_ms, 1),
            token_usage=None,
        )
