"""Proposal-only structuring for operator notes.

The service deliberately separates interpretation from Case mutation. A note is
first converted into reviewable proposals. Only the explicit accept endpoint in
the HTTP layer may pass one proposal to an existing deterministic Case
transition.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain import (
    HypothesisJudgment,
    InvestigationCase,
    LLMStatus,
    ObservationProvenance,
    StructuringProposal,
    StructuringProposalAcceptRequest,
    StructuringProposalKind,
)
from ..llm.bedrock_client import (
    BedrockUnavailable,
    GuardrailBlocked,
    apply_guardrail,
    build_client,
    llm_model_id,
    llm_provider,
)
from ..repositories.cases import CaseRepository
from ..repositories.investigation_store import InvestigationRepository
from .cases import (
    CaseTransitionError,
    append_operator_observation,
    assess_hypothesis,
    create_open_item,
)

LOGGER = logging.getLogger(__name__)


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StructuringProposalKind
    source_span: tuple[int, int] = (0, 0)
    confidence: float = Field(ge=0, le=1)
    missing_evidence: list[str] = Field(default_factory=list)
    suggested_observation: str | None = None
    suggested_open_item_title: str | None = None
    suggested_open_item_role: str | None = None
    target_hypothesis_id: str | None = None
    suggested_judgment: HypothesisJudgment | None = None
    suggested_reason: str = ""


STRUCTURING_SYSTEM_PROMPT = """당신은 제조 설비 이상 조사를 돕는 보조 도구입니다.

사용자 메모를 Case 상태로 바로 저장하지 말고, 검토 가능한 제안 목록만 JSON으로 반환하세요.
새로운 원인 후보나 설비 명령을 만들지 말고, 입력된 Case의 hypothesis ID만 사용할 수 있습니다.
사실과 가설을 섞지 말며, 원문에 없는 숫자·관측·판단을 추가하지 마세요.
반드시 다음 JSON 배열만 반환하세요.
각 원소 형식: {"kind":"observation|open_item|hypothesis", "source_span":[start,end],
"confidence":0.0, "missing_evidence":[], "suggested_observation":null,
"suggested_open_item_title":null, "suggested_open_item_role":null,
"target_hypothesis_id":null, "suggested_judgment":null, "suggested_reason":""}
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _proposal_id() -> str:
    return f"proposal_{uuid.uuid4().hex}"


def _deterministic_drafts(note: str) -> list[_Draft]:
    """Create conservative proposals without guessing a cause."""

    lowered = note.lower()
    drafts = [
        _Draft(
            kind="observation",
            source_span=(0, len(note)),
            confidence=1.0,
            suggested_observation=note,
        )
    ]
    action_markers = (
        "미확인",
        "확인 필요",
        "확인해야",
        "아직 확인",
        "다음 교대",
        "check",
        "unknown",
        "not checked",
    )
    if any(marker in lowered for marker in action_markers):
        drafts.append(
            _Draft(
                kind="open_item",
                source_span=(0, len(note)),
                confidence=0.9,
                missing_evidence=["원문 메모에 언급된 미확인 항목의 직접 관측"],
                suggested_open_item_title="메모에 언급된 미확인 항목을 확인하고 결과를 기록",
                suggested_open_item_role="operator",
            )
        )
    return drafts


def _case_context(case: InvestigationCase) -> str:
    hypotheses = [
        {"id": item.id, "candidate_signal": item.candidate_signal, "judgment": item.judgment.value}
        for item in case.hypotheses
    ]
    observations = [
        {"id": item.id, "text": item.original_text, "author": item.author}
        for item in case.observations[-10:]
    ]
    open_items = [
        {"id": item.id, "title": item.title, "status": item.status.value}
        for item in case.open_items
        if item.status.value != "resolved"
    ]
    return json.dumps(
        {
            "case_id": case.id,
            "case_version": case.version,
            "case_status": case.status.value,
            "hypotheses": hypotheses,
            "observations": observations,
            "open_items": open_items,
        },
        ensure_ascii=False,
    )


def _response_text(response: object) -> str:
    if llm_provider() == "competition_gateway":
        return getattr(response.choices[0].message, "content", "") or ""  # type: ignore[attr-defined]
    return "".join(block.text for block in response.content if block.type == "text")  # type: ignore[attr-defined]


def _parse_json(text: str) -> list[_Draft]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    payload = json.loads(cleaned)
    if not isinstance(payload, list):
        raise ValueError("Structuring response must be a JSON array")
    return [_Draft.model_validate(item) for item in payload]


def _try_llm_drafts(case: InvestigationCase, note: str) -> tuple[list[_Draft], LLMStatus]:
    prompt = (
        f"Case context (read-only): {_case_context(case)}\n\n"
        f"Operator note (the only text that may be quoted): {note}"
    )
    apply_guardrail(prompt, "INPUT")
    client = build_client()
    if llm_provider() == "competition_gateway":
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=llm_model_id("structuring"),
            max_tokens=900,
            temperature=0,
            messages=[
                {"role": "system", "content": STRUCTURING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    else:
        response = client.messages.create(  # type: ignore[attr-defined]
            model=llm_model_id("structuring"),
            max_tokens=900,
            temperature=0,
            system=STRUCTURING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    text = _response_text(response)
    apply_guardrail(text, "OUTPUT")
    return _parse_json(text), LLMStatus.GENERATED


def _validate_draft(draft: _Draft, case: InvestigationCase, note: str) -> None:
    start, end = draft.source_span
    if start < 0 or end < start or end > len(note):
        raise ValueError("Structuring source span is outside the operator note")
    if draft.kind == "hypothesis":
        if not draft.target_hypothesis_id or not any(
            item.id == draft.target_hypothesis_id for item in case.hypotheses
        ):
            raise ValueError("Structuring hypothesis must reference an existing hypothesis")
        if draft.suggested_judgment is None:
            raise ValueError("Structuring hypothesis must include a proposed judgment")
    if draft.kind == "open_item" and not draft.suggested_open_item_title:
        raise ValueError("Structuring open item must include a title")
    if draft.kind == "observation" and not draft.suggested_observation:
        raise ValueError("Structuring observation must include text")


def _to_proposal(
    *,
    draft: _Draft,
    case: InvestigationCase,
    note: str,
    author: str,
    observed_at: str | None,
    scope: str,
    source_location: str,
    provenance: ObservationProvenance,
    llm_status: LLMStatus,
) -> StructuringProposal:
    role = draft.suggested_open_item_role
    if role not in {"operator", "process_expert", "equipment_expert"}:
        role = "operator" if draft.kind == "open_item" else None
    return StructuringProposal(
        id=_proposal_id(),
        case_id=case.id,
        case_version=case.version,
        kind=draft.kind,
        source_text=note,
        source_span=draft.source_span,
        confidence=draft.confidence,
        missing_evidence=draft.missing_evidence,
        suggested_observation=draft.suggested_observation,
        suggested_open_item_title=draft.suggested_open_item_title,
        suggested_open_item_role=role,  # type: ignore[arg-type]
        target_hypothesis_id=draft.target_hypothesis_id,
        suggested_judgment=draft.suggested_judgment,
        suggested_reason=draft.suggested_reason,
        author=author,
        observed_at=observed_at,
        scope=scope,
        source_location=source_location,
        provenance=provenance,
        llm_status=llm_status,
        generator="llm" if llm_status is LLMStatus.GENERATED else "deterministic",
        created_at=_now(),
    )


def build_structuring_proposals(
    *,
    case: InvestigationCase,
    note: str,
    author: str,
    observed_at: str | None,
    scope: str,
    source_location: str,
    provenance: ObservationProvenance,
    include_llm: bool,
) -> list[StructuringProposal]:
    status = LLMStatus.NOT_REQUESTED
    drafts: list[_Draft]
    if include_llm:
        try:
            drafts, status = _try_llm_drafts(case, note)
            drafts = [draft for draft in drafts if _safe_draft(draft, case, note)]
            if not drafts:
                raise ValueError("LLM returned no valid structuring proposals")
        except GuardrailBlocked:
            LOGGER.info("Structuring request was blocked by the configured guardrail")
            drafts, status = _deterministic_drafts(note), LLMStatus.BLOCKED
        except (BedrockUnavailable, ValueError, json.JSONDecodeError):
            LOGGER.info("Structuring LLM unavailable; using deterministic proposals", exc_info=True)
            drafts, status = _deterministic_drafts(note), LLMStatus.UNAVAILABLE
        except Exception:
            LOGGER.exception("Unexpected structuring failure; using deterministic proposals")
            drafts, status = _deterministic_drafts(note), LLMStatus.UNAVAILABLE
    else:
        drafts = _deterministic_drafts(note)
    return [
        _to_proposal(
            draft=draft,
            case=case,
            note=note,
            author=author,
            observed_at=observed_at,
            scope=scope,
            source_location=source_location,
            provenance=provenance,
            llm_status=status,
        )
        for draft in drafts
    ]


def _safe_draft(draft: _Draft, case: InvestigationCase, note: str) -> bool:
    try:
        _validate_draft(draft, case, note)
    except ValueError:
        return False
    return True


def accept_structuring_proposal(
    *,
    proposal: StructuringProposal,
    request: StructuringProposalAcceptRequest,
    investigations: InvestigationRepository,
    cases: CaseRepository,
) -> Any:
    """Apply exactly one reviewed proposal through an existing Case mutation."""

    if proposal.kind == "observation":
        return append_operator_observation(
            case_id=proposal.case_id,
            original_text=(
                request.edited_text or proposal.suggested_observation or proposal.source_text
            ),
            author=proposal.author,
            observed_at=proposal.observed_at,
            scope=proposal.scope,
            source_location=proposal.source_location,
            provenance=proposal.provenance,
            is_current_state=False,
            expected_version=request.expected_version,
            cases=cases,
        )
    if proposal.kind == "open_item":
        return create_open_item(
            case_id=proposal.case_id,
            title=proposal.suggested_open_item_title or proposal.source_text[:240],
            requested_role=proposal.suggested_open_item_role or "operator",
            assignee=None,
            due_at=None,
            run_id=None,
            evidence_ids=[],
            expected_version=request.expected_version,
            investigations=investigations,
            cases=cases,
        )
    if proposal.target_hypothesis_id and proposal.suggested_judgment:
        return assess_hypothesis(
            case_id=proposal.case_id,
            hypothesis_id=proposal.target_hypothesis_id,
            judgment=proposal.suggested_judgment,
            updated_by=request.accepted_by,
            change_reason=(
                proposal.suggested_reason
                or "Accepted from a reviewed structuring proposal."
            ),
            supporting_observation_ids=[],
            opposing_evidence_ids=[],
            expected_version=request.expected_version,
            investigations=investigations,
            cases=cases,
        )
    raise CaseTransitionError("Structuring proposal is incomplete")
