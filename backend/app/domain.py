"""Shared, runtime-safe contracts for the investigation service."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetName(str, Enum):
    CAUSRCA = "causrca"
    METAL_ETCH = "metal_etch"


class Capability(str, Enum):
    TIME_SERIES = "time_series"
    MULTI_SOURCE_EVIDENCE = "multi_source_evidence"
    ROOT_CAUSE_RANKING = "root_cause_ranking"
    CAUSAL_GRAPH = "causal_graph"


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def start_precedes_end(self) -> "TimeRange":
        if self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_s: float = Field(ge=0)
    signal: str = Field(min_length=1, max_length=120)
    value: str | float | int | bool
    kind: Literal["Alarm", "Measurement", "Event"]


class Incident(BaseModel):
    """Only information available before a diagnosis cutoff may enter this model."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source_dataset: DatasetName
    title: str = Field(min_length=1, max_length=200)
    time_range_s: TimeRange
    capabilities: set[Capability] = Field(default_factory=set)
    observations: list[Observation] = Field(default_factory=list)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    detail: str
    source: str


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    signal: str
    reason: str
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["candidate", "inconclusive"] = "candidate"


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    tool: str
    detail: str
    # Additive fields (ADR-0002): populated when a step involves an LLM call.
    # Deterministic-only steps leave these as None -- absence of a number is
    # itself meaningful ("no LLM was used here"), not a missing measurement.
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: int | None = Field(default=None, ge=0)


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_time: float = Field(ge=0)
    question: str = Field(default="", max_length=2000)
    # Default False (ADR-0002): the deterministic workflow must fully function
    # with no LLM configured. Callers opt in explicitly per request.
    include_llm_narrative: bool = False


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    dataset: DatasetName
    diagnosis_time: float
    # "deterministic_with_llm_narrative" is only used when include_llm_narrative
    # was requested AND the narrative was actually generated (ADR-0002). If the
    # LLM call fails or is unavailable, mode stays "deterministic" and
    # llm_narrative stays None -- the API never silently claims LLM involvement
    # that did not happen.
    mode: Literal["deterministic", "deterministic_with_llm_narrative"] = "deterministic"
    candidates: list[Candidate]
    evidence: list[Evidence]
    trace: list[TraceEvent]
    warnings: list[str]
    next_action: str
    llm_narrative: str | None = None


class ReviewDecision(BaseModel):
    """Human-in-the-loop review of one investigation (2-A)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)
    reviewer: str = Field(min_length=1, max_length=120)


class StoredReview(BaseModel):
    """A recorded review, persisted alongside its investigation id."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    decision: Literal["approve", "reject"]
    comment: str
    reviewer: str
    reviewed_at: str


class InvestigationReport(BaseModel):
    """Final report: the investigation result plus any recorded reviews."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    result: InvestigationResult
    reviews: list[StoredReview]
