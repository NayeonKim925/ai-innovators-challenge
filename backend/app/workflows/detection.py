"""Fault-detection agent: decide the next action from two deterministic signals.

See `docs/AGENT_FAULT_DETECTION_PLAN.md` sections 3-4. Phase 1 shipped a
single signal (alarm activation) with a two-way decision. Phase 2 adds a
second, independent signal (PCA anomaly score against a real_op
normal-operation baseline, `analytics/causrca_anomaly.py`) and expands the
decision into the four-way branch documented on `FaultDetectionResult`. Both
signal-observing nodes are deterministic tools; only `decide_next_action`
does agent-style judgment, and even that judgment is a fixed, auditable rule
table -- no signal's underlying number is invented or adjusted here. The
state shape and node signatures stay plain-function/TypedDict so a later
AgentCore Runtime can wrap this graph as a tool without a rewrite (ADR-0005
section 6).
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..analytics.causrca_anomaly import compute_anomaly_score
from ..analytics.fault_onset import estimate_fault_onset
from ..domain import Evidence, FaultDetectionResult, Incident, TraceEvent


class DetectionState(TypedDict, total=False):
    incident: Incident
    observed_up_to_s: float
    onset_time_s: float | None
    anomaly_score: float | None
    anomaly_threshold: float | None
    evidence: list[Evidence]
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
        "evidence": [evidence] if evidence is not None else [],
        "trace": [TraceEvent(step=1, tool="alarm_activation_onset_estimator", detail=detail)],
    }


def observe_anomaly_score(state: DetectionState) -> dict:
    incident = state["incident"]
    score, threshold, evidence, warnings = compute_anomaly_score(
        incident, state["observed_up_to_s"]
    )
    if score is None:
        detail = f"PCA anomaly score unavailable: {warnings[0] if warnings else 'unknown reason'}"
    else:
        elevated = "elevated" if threshold is not None and score >= threshold else "normal"
        detail = f"PCA reconstruction error={score:.3g} ({elevated}, threshold={threshold:.3g})."
    return {
        "anomaly_score": score,
        "anomaly_threshold": threshold,
        "evidence": state["evidence"] + ([evidence] if evidence is not None else []),
        "trace": state["trace"]
        + [TraceEvent(step=2, tool="pca_anomaly_score", detail=detail)],
    }


def decide_next_action(state: DetectionState) -> dict:
    onset = state["onset_time_s"]
    score = state["anomaly_score"]
    threshold = state["anomaly_threshold"]
    elevated = score is not None and threshold is not None and score >= threshold

    if onset is not None and (score is None or elevated):
        decision = "trigger_rca"
        signal_note = (
            "and the anomaly score corroborates it" if elevated else "(anomaly score unavailable)"
        )
        detail = (
            f"An active alarm was observed {signal_note}; handing off to root-cause "
            "ranking at the alarm time."
        )
    elif onset is not None:
        decision = "false_positive_review"
        detail = (
            "An alarm is active but the PCA anomaly score is still within the normal-operation "
            "range; a human should check for a possible false alarm before root-cause ranking."
        )
    elif elevated:
        decision = "elevated_watch"
        detail = (
            "No alarm has activated yet, but the anomaly score already exceeds the "
            "normal-operation range; the agent continues close observation."
        )
    else:
        decision = "await_more_data"
        detail = "Neither signal indicates a problem yet; the agent continues watching the stream."

    return {
        "decision": decision,
        "trace": state["trace"]
        + [TraceEvent(step=3, tool="fault_detection_decision", detail=detail)],
    }


_builder = StateGraph(DetectionState)
_builder.add_node("observe_alarms", observe_alarms)
_builder.add_node("observe_anomaly_score", observe_anomaly_score)
_builder.add_node("decide_next_action", decide_next_action)
_builder.add_edge(START, "observe_alarms")
_builder.add_edge("observe_alarms", "observe_anomaly_score")
_builder.add_edge("observe_anomaly_score", "decide_next_action")
_builder.add_edge("decide_next_action", END)
_graph = _builder.compile()


def detect_fault_onset(incident: Incident, observed_up_to_s: float) -> FaultDetectionResult:
    """Run the detection agent over an incident's observations, up to a playback position."""

    state = _graph.invoke(
        {"incident": incident, "observed_up_to_s": observed_up_to_s},
        {"recursion_limit": 6},
    )
    return FaultDetectionResult(
        incident_id=incident.id,
        observed_up_to_s=observed_up_to_s,
        onset_time_s=state["onset_time_s"],
        anomaly_score=state["anomaly_score"],
        anomaly_threshold=state["anomaly_threshold"],
        decision=state["decision"],
        evidence=state["evidence"],
        trace=state["trace"],
    )
