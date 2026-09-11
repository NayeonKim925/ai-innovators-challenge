"""Read-only investigation workflow with explicit tool trace."""

from __future__ import annotations

import math
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..analytics.causrca import rank_with_caus_tr
from ..analytics.recency_baseline import rank_active_alarms
from ..domain import DatasetName, Incident, InvestigationResult, TraceEvent


class InvestigationState(TypedDict, total=False):
    incident: Incident
    diagnosis_time: float
    question: str
    candidates: list
    evidence: list
    warnings: list[str]
    trace: list[TraceEvent]


def validate_request(state: InvestigationState) -> dict:
    incident = state["incident"]
    cutoff = state["diagnosis_time"]
    if not math.isfinite(cutoff) or not incident.time_range_s.start <= cutoff <= incident.time_range_s.end:
        raise ValueError("diagnosis_time must be within the runtime incident range")
    return {
        "warnings": [],
        "trace": [
            TraceEvent(
                step=1,
                tool="validate_request",
                detail="Validated incident identifier and explicit diagnosis cutoff. The question is recorded, not executed.",
            )
        ],
    }


def run_deterministic_analysis(state: InvestigationState) -> dict:
    incident = state["incident"]
    tool = "active_alarm_recency_baseline"
    candidates = []
    evidence = []
    warnings = list(state["warnings"])
    if incident.source_dataset is DatasetName.CAUSRCA:
        candidates, evidence, tool_warnings = rank_with_caus_tr(incident, state["diagnosis_time"])
        warnings.extend(tool_warnings)
        if candidates:
            tool = "causrca_causal_prio_time_recency"
    if not candidates:
        candidates, evidence = rank_active_alarms(incident, state["diagnosis_time"])
    if not candidates:
        warnings.append("No active alarm was observed before the cutoff; the workflow abstains from a root-cause ranking.")
    return {
        "candidates": candidates,
        "evidence": evidence,
        "warnings": warnings,
        "trace": state["trace"]
        + [
            TraceEvent(
                step=2,
                tool=tool,
                detail="Ranked runtime observations only. No evaluation labels or LLM calls were used.",
            )
        ],
    }


def assemble_review(state: InvestigationState) -> dict:
    return {
        "trace": state["trace"]
        + [
            TraceEvent(
                step=3,
                tool="prepare_human_review",
                detail="Prepared evidence-linked candidates for expert review; no repair instruction or physical action was generated.",
            )
        ]
    }


_builder = StateGraph(InvestigationState)
_builder.add_node("validate_request", validate_request)
_builder.add_node("run_deterministic_analysis", run_deterministic_analysis)
_builder.add_node("assemble_review", assemble_review)
_builder.add_edge(START, "validate_request")
_builder.add_edge("validate_request", "run_deterministic_analysis")
_builder.add_edge("run_deterministic_analysis", "assemble_review")
_builder.add_edge("assemble_review", END)
_graph = _builder.compile()


def investigate(incident: Incident, diagnosis_time: float, question: str = "") -> InvestigationResult:
    state = _graph.invoke(
        {"incident": incident, "diagnosis_time": diagnosis_time, "question": question},
        {"recursion_limit": 6},
    )
    candidates = state["candidates"]
    next_action = (
        "Compare each candidate with process documentation and the observed signal history."
        if candidates
        else "Collect additional observations before proposing a root-cause candidate."
    )
    return InvestigationResult(
        incident_id=incident.id,
        dataset=incident.source_dataset,
        diagnosis_time=diagnosis_time,
        candidates=candidates,
        evidence=state["evidence"],
        trace=state["trace"],
        warnings=state["warnings"]
        + ["This is a research investigation aid. Candidates require explicit expert review."],
        next_action=next_action,
    )
