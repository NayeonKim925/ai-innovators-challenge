"""Shared, runtime-safe contracts for the investigation service."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetName(str, Enum):
    CAUSRCA = "causrca"
    METAL_ETCH = "metal_etch"


class LLMStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    RUNNING = "running"
    GENERATED = "generated"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"


class CaseStatus(str, Enum):
    """Human-in-the-loop state of an investigation case.

    A case is intentionally distinct from an InvestigationResult. The result
    records what a deterministic tool observed at a cutoff; the case records
    what still needs a human response before the investigation can be closed.
    """

    AWAITING_EVIDENCE = "awaiting_evidence"
    READY_FOR_REVIEW = "ready_for_review"
    REOPENED = "reopened"
    ABSTAINED = "abstained"
    CLOSED = "closed"


class EvidenceTaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class ExpertResponseOutcome(str, Enum):
    """Outcome of an evidence check, never a root-cause confirmation."""

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNAVAILABLE = "unavailable"


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
    def start_precedes_end(self) -> TimeRange:
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
    # Production deployments can return the deterministic result immediately
    # and generate the Bedrock narrative from a durable queue afterwards.
    async_llm_narrative: bool = False


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    grounded_evidence_ids: list[str] = Field(default_factory=list)
    blocked: bool = False
    llm_status: LLMStatus = LLMStatus.NOT_REQUESTED
    trace: TraceEvent | None = None


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    dataset: DatasetName
    diagnosis_time: float
    question: str = ""
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
    llm_status: LLMStatus = LLMStatus.NOT_REQUESTED


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


class CaseCreateRequest(BaseModel):
    """Starts a stateful case without opting into an LLM call."""

    model_config = ConfigDict(extra="forbid")

    diagnosis_time: float = Field(ge=0)
    question: str = Field(default="", max_length=2000)


class ExpertTaskResponse(BaseModel):
    """A bounded expert response to a requested evidence check.

    ``confirmed`` means the expert could confirm the stated observation or
    documentation comparison, not that a candidate is the real physical cause.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: ExpertResponseOutcome
    comment: str = Field(default="", max_length=2000)
    responder: str = Field(min_length=1, max_length=120)


class EvidenceTask(BaseModel):
    """A human action the case must resolve before it can progress."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    kind: Literal["verify_candidate", "collect_observation"]
    status: EvidenceTaskStatus = EvidenceTaskStatus.PENDING
    requested_role: Literal["operator", "process_expert", "equipment_expert"]
    title: str = Field(min_length=1, max_length=240)
    instructions: str = Field(min_length=1, max_length=2000)
    candidate_signal: str | None = Field(default=None, max_length=120)
    evidence_ids: list[str] = Field(default_factory=list)
    trace_steps: list[int] = Field(default_factory=list)
    response: ExpertTaskResponse | None = None
    created_at: str
    completed_at: str | None = None


class CaseEvent(BaseModel):
    """Persisted event used by the UI as an auditable agent run ledger."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    event_type: Literal[
        "analysis_completed",
        "evidence_task_created",
        "expert_response_recorded",
        "case_ready_for_review",
        "case_reopened",
        "case_abstained",
        "case_closed",
    ]
    detail: str = Field(min_length=1, max_length=2000)
    actor: Literal["case_orchestrator", "expert"]
    evidence_ids: list[str] = Field(default_factory=list)
    trace_steps: list[int] = Field(default_factory=list)
    created_at: str


class CaseReviewDecision(BaseModel):
    """Final human decision for a case whose required evidence work is done."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)
    reviewer: str = Field(min_length=1, max_length=120)


class StoredCaseReview(CaseReviewDecision):
    reviewed_at: str


class InvestigationCase(BaseModel):
    """A case binds an immutable deterministic investigation to human follow-up."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    incident_id: str
    dataset: DatasetName
    investigation_id: str
    status: CaseStatus
    version: int = Field(default=0, ge=0)
    next_action: str = Field(min_length=1, max_length=2000)
    tasks: list[EvidenceTask] = Field(default_factory=list)
    events: list[CaseEvent] = Field(default_factory=list)
    reviews: list[StoredCaseReview] = Field(default_factory=list)
    created_at: str
    updated_at: str
