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


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_time: float = Field(ge=0)
    question: str = Field(default="", max_length=2000)


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    dataset: DatasetName
    diagnosis_time: float
    mode: Literal["deterministic"] = "deterministic"
    candidates: list[Candidate]
    evidence: list[Evidence]
    trace: list[TraceEvent]
    warnings: list[str]
    next_action: str
