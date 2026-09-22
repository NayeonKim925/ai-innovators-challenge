"""Phase 1 fault-detection agent: decide whether to trigger RCA, deterministically.

See `docs/AGENT_FAULT_DETECTION_PLAN.md` section 3. This graph is intentionally
small for Phase 1 (one signal: alarm activation). Phase 2 adds a PCA anomaly
score and expands `decide_next_action` into the four-way branch documented in
the plan (await_more_data / false_positive_review / trigger_rca / retry). The
state shape and node signatures are kept plain-function/TypedDict so a later
AgentCore Runtime can wrap this graph as a tool without a rewrite (ADR-0005
section 6).
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..analytics.fault_onset import estimate_fault_onset
from ..domain import Evidence, FaultDetectionResult, Incident, TraceEvent


class DetectionState(TypedDict, total=False):
    incident: Incident
    observed_up_to_s: float
    onset_time_s: float | None
    evidence: Evidence | None
    decision: str
    trace: list[TraceEvent]


def observe_alarms(state: DetectionState) -> dict:
    incident = state["incident"]
    onset_time_s, evidence = estimate_fault_onset(incident, state["observed_up_to_s"])
    detail = (
        f"Scanned observations up to t={state['observed_up_to_s']:g}s for active alarms; "
        + (f"earliest found at t={onset_time_s:g}s." if onset_time_s is not None else "none found.")
    )
    return {
        "onset_time_s": onset_time_s,
        "evidence": evidence,
        "trace": [TraceEvent(step=1, tool="alarm_activation_onset_estimator", detail=detail)],
    }


def decide_next_action(state: DetectionState) -> dict:
    decision = "trigger_rca" if state["onset_time_s"] is not None else "await_more_data"
    detail = (
        "An active alarm was observed; handing off to root-cause ranking at the alarm time."
        if decision == "trigger_rca"
        else "No active alarm has been observed yet; the agent continues watching the stream."
    )
    return {
        "decision": decision,
        "trace": state["trace"]
        + [TraceEvent(step=2, tool="fault_detection_decision", detail=detail)],
    }


_builder = StateGraph(DetectionState)
_builder.add_node("observe_alarms", observe_alarms)
_builder.add_node("decide_next_action", decide_next_action)
_builder.add_edge(START, "observe_alarms")
_builder.add_edge("observe_alarms", "decide_next_action")
_builder.add_edge("decide_next_action", END)
_graph = _builder.compile()


def detect_fault_onset(incident: Incident, observed_up_to_s: float) -> FaultDetectionResult:
    """Run the detection agent over an incident's observations, up to a playback position."""

    state = _graph.invoke(
        {"incident": incident, "observed_up_to_s": observed_up_to_s},
        {"recursion_limit": 4},
    )
    return FaultDetectionResult(
        incident_id=incident.id,
        observed_up_to_s=observed_up_to_s,
        onset_time_s=state["onset_time_s"],
        decision=state["decision"],
        evidence=state["evidence"],
        trace=state["trace"],
    )
