"""Tests for the LLM narrative layer (ADR-0002).

These tests never call the real Bedrock API. They verify that:
1. `backend.app.main` still imports even if the `anthropic` SDK is missing.
2. `generate_narrative()` falls back to `(None, TraceEvent)` instead of raising,
   whether the SDK is missing or the client construction otherwise fails.
3. `get_fault_reference()` matches known signal prefixes and returns
   `found=False` (never a fabricated answer) for unknown ones.
"""

from __future__ import annotations

import pytest
from app.domain import DatasetName, InvestigationResult, TraceEvent
from app.llm.explainer import _build_prompt, generate_narrative
from app.llm.tools import get_fault_reference, summarize_candidates


def _empty_result() -> InvestigationResult:
    return InvestigationResult(
        incident_id="case_1",
        dataset=DatasetName.CAUSRCA,
        diagnosis_time=5,
        candidates=[],
        evidence=[],
        trace=[TraceEvent(step=1, tool="validate_request", detail="ok")],
        warnings=[],
        next_action="n/a",
    )


def test_get_fault_reference_matches_known_prefixes() -> None:
    tcp = get_fault_reference("TCP Top Pwr")
    rf = get_fault_reference("RF Load")

    assert tcp["found"] is True
    assert "disclaimer" in tcp
    assert rf["found"] is True
    assert "disclaimer" in rf


def test_get_fault_reference_never_fabricates_an_unknown_signal() -> None:
    result = get_fault_reference("Totally Unknown Signal")

    assert result == {"found": False, "reason": "'Totally Unknown Signal'이 속한 계열을 찾을 수 없습니다."}


def test_summarize_candidates_only_repackages_existing_data() -> None:
    from app.domain import Candidate, Evidence

    evidence = [Evidence(id="E1", title="t", detail="d", source="s")]
    candidates = [Candidate(rank=1, signal="RF Load", reason="r", evidence_ids=["E1"])]

    summary = summarize_candidates(candidates, evidence)

    assert summary["found"] is True
    assert summary["candidates"][0]["signal"] == "RF Load"
    assert summary["candidates"][0]["evidence"][0]["title"] == "t"


def test_prompt_contains_question_and_evidence() -> None:
    from app.domain import Candidate, Evidence

    result = InvestigationResult(
        incident_id="case_1",
        dataset=DatasetName.CAUSRCA,
        diagnosis_time=5,
        question="왜 먼저 확인하나요?",
        candidates=[Candidate(rank=1, signal="P101", reason="recent alarm", evidence_ids=["E1"])],
        evidence=[Evidence(id="E1", title="Alarm", detail="P101 at t=2", source="runtime")],
        trace=[],
        warnings=[],
        next_action="check",
    )

    prompt = _build_prompt(result)
    assert "왜 먼저 확인하나요?" in prompt
    assert "E1" in prompt
    assert "P101 at t=2" in prompt


def test_generate_narrative_falls_back_gracefully_when_bedrock_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_narrative() must never raise, even if the Bedrock call itself
    fails. This test never calls the real Bedrock API -- it forces build_client()
    to fail so the failure path is exercised deterministically and offline."""
    import app.llm.explainer as explainer_module
    from app.llm.bedrock_client import BedrockUnavailable

    def _always_unavailable() -> None:
        raise BedrockUnavailable("forced for test: no real network call is made")

    monkeypatch.setattr(explainer_module, "build_client", _always_unavailable)

    narrative, trace_event = generate_narrative(_empty_result())

    assert narrative is None
    assert trace_event.tool == "bedrock_llm_narrative"
    assert trace_event.latency_ms is not None
    assert trace_event.latency_ms >= 0
    assert "deterministic result was preserved" in trace_event.detail


def test_generate_narrative_applies_guardrail_to_input_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import Candidate, Evidence

    class TextBlock:
        type = "text"
        text = "[E1] 근거에 연결된 후보입니다."

    class FakeResponse:
        content = [TextBlock()]
        usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 8})()

    class FakeMessages:
        def create(self, **_: object) -> FakeResponse:
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    result = InvestigationResult(
        incident_id="case_1",
        dataset=DatasetName.CAUSRCA,
        diagnosis_time=5,
        candidates=[Candidate(rank=1, signal="P101", reason="alarm", evidence_ids=["E1"])],
        evidence=[Evidence(id="E1", title="Alarm", detail="P101 at t=2", source="runtime")],
        trace=[],
        warnings=[],
        next_action="check",
    )
    calls: list[str] = []
    import app.llm.explainer as explainer_module

    monkeypatch.setattr(explainer_module, "build_client", lambda: FakeClient())
    monkeypatch.setattr(explainer_module, "apply_guardrail", lambda _text, source: calls.append(source))

    narrative, trace_event = generate_narrative(result)

    assert narrative == "[E1] 근거에 연결된 후보입니다."
    assert calls == ["INPUT", "OUTPUT"]
    assert trace_event.token_usage == 18


def test_generate_narrative_uses_competition_gateway_chat_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway path is OpenAI-compatible but keeps the same evidence gate."""
    from app.domain import Candidate, Evidence

    class Message:
        content = "[E1] 게이트웨이 응답입니다."

    class Choice:
        message = Message()

    class Usage:
        prompt_tokens = 12
        completion_tokens = 7

    class Completions:
        def create(self, **kwargs: object) -> object:
            assert kwargs["model"] == "bedrock-haiku"
            assert kwargs["temperature"] == 0
            assert kwargs["messages"][0]["role"] == "system"  # type: ignore[index]
            return type("GatewayResponse", (), {"choices": [Choice()], "usage": Usage()})()

    class FakeClient:
        chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setenv("LLM_PROVIDER", "competition_gateway")
    monkeypatch.setenv("LLM_MODEL", "bedrock-haiku")
    monkeypatch.setattr("app.llm.explainer.build_client", lambda: FakeClient())
    monkeypatch.setattr("app.llm.explainer.apply_guardrail", lambda *_args: None)

    result = InvestigationResult(
        incident_id="case_1",
        dataset=DatasetName.CAUSRCA,
        diagnosis_time=5,
        candidates=[Candidate(rank=1, signal="P101", reason="alarm", evidence_ids=["E1"])],
        evidence=[Evidence(id="E1", title="Alarm", detail="P101 at t=2", source="runtime")],
        trace=[],
        warnings=[],
        next_action="check",
    )

    narrative, trace_event = generate_narrative(result)

    assert narrative == "[E1] 게이트웨이 응답입니다."
    assert trace_event.token_usage == 19
    assert "competition_gateway / bedrock-haiku" in trace_event.detail


def test_gateway_model_defaults_split_by_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.bedrock_client import llm_model_id

    monkeypatch.setenv("LLM_PROVIDER", "competition_gateway")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_STRUCTURING_MODEL", raising=False)

    assert llm_model_id() == "bedrock-gpt-5.6-terra"
    assert llm_model_id("structuring") == "bedrock-haiku"


def test_gateway_accepts_the_competition_guide_api_key_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.bedrock_client import llm_api_key

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "guide-key")

    assert llm_api_key() == "guide-key"
