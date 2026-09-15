"""Tests for the orchestration layer added in 2-A/2-B.

`run_investigation()` sits between the pure deterministic workflow and the
optional LLM narrative step. These tests never call the real Bedrock API --
they monkeypatch `generate_narrative` (like `test_llm_narrative.py` does for
`build_client`) so the LLM path is exercised deterministically and offline.
"""

from __future__ import annotations

import pytest
from app.domain import (
    Capability,
    DatasetName,
    Incident,
    Observation,
    TimeRange,
    TraceEvent,
)
from app.services.investigations import run_investigation


def _incident() -> Incident:
    return Incident(
        id="case_1",
        source_dataset=DatasetName.CAUSRCA,
        title="Prepared incident",
        time_range_s=TimeRange(start=0, end=10),
        capabilities={Capability.TIME_SERIES, Capability.ROOT_CAUSE_RANKING},
        observations=[Observation(time_s=2, signal="P101", value=True, kind="Alarm")],
    )


def test_run_investigation_without_llm_stays_deterministic() -> None:
    result = run_investigation(
        _incident(), diagnosis_time=3, question="", include_llm_narrative=False
    )

    assert result.mode == "deterministic"
    assert result.llm_narrative is None
    assert "bedrock_llm_narrative" not in [event.tool for event in result.trace]


def test_run_investigation_with_llm_appends_narrative_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.investigations as service_module

    def _fake_generate_narrative(result):
        return "요약: P101이 유력 후보입니다.", TraceEvent(
            step=5,
            tool="bedrock_llm_narrative",
            detail="fake success",
            latency_ms=1.0,
            token_usage=10,
        )

    monkeypatch.setattr(service_module, "generate_narrative", _fake_generate_narrative)

    result = run_investigation(
        _incident(), diagnosis_time=3, question="", include_llm_narrative=True
    )

    assert result.mode == "deterministic_with_llm_narrative"
    assert result.llm_narrative == "요약: P101이 유력 후보입니다."
    assert result.trace[-1].tool == "bedrock_llm_narrative"
    # The deterministic candidates/evidence must be untouched by the LLM step.
    assert result.candidates[0].signal == "P101"


def test_run_investigation_with_llm_falls_back_when_narrative_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.investigations as service_module

    def _fake_generate_narrative(result):
        return None, TraceEvent(
            step=5,
            tool="bedrock_llm_narrative",
            detail="fake failure, no network call",
            latency_ms=1.0,
        )

    monkeypatch.setattr(service_module, "generate_narrative", _fake_generate_narrative)

    result = run_investigation(
        _incident(), diagnosis_time=3, question="", include_llm_narrative=True
    )

    assert result.mode == "deterministic"
    assert result.llm_narrative is None
    assert result.trace[-1].tool == "bedrock_llm_narrative"
