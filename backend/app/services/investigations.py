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

from ..domain import Incident, InvestigationResult
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
    narrative, trace_event = generate_narrative(result)
    updates: dict[str, object] = {"trace": [*result.trace, trace_event]}
    if narrative is not None:
        updates["mode"] = "deterministic_with_llm_narrative"
        updates["llm_narrative"] = narrative
    return result.model_copy(update=updates)
