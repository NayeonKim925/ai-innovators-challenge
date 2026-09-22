"""Composes the fault-detection agent with the existing RCA investigation.

`workflows/detection.py` decides *whether* enough evidence exists to hand off
to root-cause ranking; this module is the one place that performs that
hand-off, mirroring how `services/investigations.py` is the one place that
decides whether to also call the LLM narrative step. Neither workflow module
imports the other's tools directly.
"""

from __future__ import annotations

from ..domain import FaultDetectionResult, Incident, InvestigationResult
from ..workflows.detection import detect_fault_onset
from .investigations import run_investigation


def run_auto_detection(
    incident: Incident,
    observed_up_to_s: float,
    question: str = "",
    include_llm_narrative: bool = False,
) -> tuple[FaultDetectionResult, InvestigationResult | None]:
    """Detect a fault onset and, if found, automatically run RCA at that time.

    Returns the detection result always, and an `InvestigationResult` only when
    the agent decided `trigger_rca`. The investigation's trace is renumbered to
    continue after the detection trace so the combined `TraceEvent` sequence in
    the API response reads as one continuous, auditable agent run.
    """
    detection = detect_fault_onset(incident, observed_up_to_s)
    if detection.decision != "trigger_rca" or detection.onset_time_s is None:
        return detection, None

    investigation = run_investigation(
        incident, detection.onset_time_s, question, include_llm_narrative
    )
    offset = len(detection.trace)
    renumbered_trace = [
        event.model_copy(update={"step": event.step + offset}) for event in investigation.trace
    ]
    investigation = investigation.model_copy(
        update={
            "trace": renumbered_trace,
            "warnings": [
                "diagnosis_time was set automatically by the fault-detection agent "
                "from the earliest observed active alarm, not chosen by a human.",
                *investigation.warnings,
            ],
        }
    )
    return detection, investigation
