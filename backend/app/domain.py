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


class OpenItemStatus(str, Enum):
    NOT_STARTED = "not_started"
    UNAVAILABLE = "unavailable"
    NOT_RECORDED = "not_recorded"
    RESOLVED = "resolved"
    ON_HOLD = "on_hold"


class HypothesisJudgment(str, Enum):
    UNREVIEWED = "unreviewed"
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT = "insufficient"


class ObservationProvenance(str, Enum):
    ACTUAL = "actual"
    SYNTHETIC_DEMO = "synthetic_demo"
    SIMULATED = "simulated"


class HandoverStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CHANGES_REQUESTED = "changes_requested"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class HandoverFindingSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


ActorRole = Literal[
    "operator",
    "shift_lead",
    "supervisor",
    "maintenance_lead",
    "admin",
]


class ActorContext(BaseModel):
    """Trusted identity context attached to a state-changing Case action."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=120)
    role: ActorRole
    source: Literal["trusted_header", "local_fallback"] = "trusted_header"


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


class CaseChatRequest(ChatRequest):
    include_llm: bool = False


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


class ExpectedVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)


class OperatorObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    original_text: str = Field(min_length=1, max_length=4000)
    author: str = Field(min_length=1, max_length=120)
    observed_at: str | None = None
    scope: str = Field(default="", max_length=500)
    source_location: str = Field(default="", max_length=500)
    provenance: ObservationProvenance = ObservationProvenance.SYNTHETIC_DEMO
    is_current_state: bool = False


class AnalysisRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    diagnosis_time: float = Field(ge=0)
    question: str = Field(default="", max_length=2000)
    created_by: str = Field(min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=160)


class OpenItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    requested_role: Literal["operator", "process_expert", "equipment_expert"]
    assignee: str | None = Field(default=None, max_length=120)
    due_at: str | None = None
    run_id: str | None = Field(default=None, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list)


class OpenItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    status: OpenItemStatus
    assignee: str | None = Field(default=None, max_length=120)
    hold_reason: str = Field(default="", max_length=2000)
    completion_note: str = Field(default="", max_length=2000)
    observation_ids: list[str] = Field(default_factory=list)


class HypothesisAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    judgment: HypothesisJudgment
    updated_by: str = Field(min_length=1, max_length=120)
    change_reason: str = Field(default="", max_length=2000)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    opposing_evidence_ids: list[str] = Field(default_factory=list)


class HandoverCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    sender: str = Field(min_length=1, max_length=120)
    receiver: str = Field(min_length=1, max_length=120)


class HandoverPublishRequest(HandoverCheckRequest):
    exception_reason: str = Field(default="", max_length=2000)


class HandoverAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    snapshot_id: str = Field(min_length=1, max_length=80)
    accepted_by: str = Field(min_length=1, max_length=120)


class HandoverChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    requested_by: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)


class ExpertTaskResponse(BaseModel):
    """A bounded expert response to a requested evidence check.

    ``confirmed`` means the expert could confirm the stated observation or
    documentation comparison, not that a candidate is the real physical cause.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: ExpertResponseOutcome
    comment: str = Field(default="", max_length=2000)
    responder: str = Field(min_length=1, max_length=120)
    # Optional for legacy clients; new Continuum clients send this explicitly.
    expected_version: int | None = Field(default=None, ge=0)


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
    # Evidence IDs are only unique inside one immutable AnalysisRun.
    run_id: str | None = Field(default=None, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list)
    trace_steps: list[int] = Field(default_factory=list)
    open_item_id: str | None = Field(default=None, max_length=80)
    response: ExpertTaskResponse | None = None
    created_at: str
    completed_at: str | None = None


class AnalysisRun(BaseModel):
    """Immutable link from a Case to one deterministic investigation result."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    investigation_id: str = Field(min_length=1, max_length=120)
    incident_id: str = Field(min_length=1, max_length=120)
    dataset: DatasetName
    diagnosis_time: float = Field(ge=0)
    algorithm_version: str = Field(min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=160)
    created_by: str = Field(min_length=1, max_length=120)
    created_at: str


class OperatorObservation(BaseModel):
    """Human-entered context, kept separate from machine sensor observations."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    original_text: str = Field(min_length=1, max_length=4000)
    author: str = Field(min_length=1, max_length=120)
    observed_at: str | None = None
    recorded_at: str
    scope: str = Field(default="", max_length=500)
    source_location: str = Field(default="", max_length=500)
    provenance: ObservationProvenance
    approved: bool = False
    is_current_state: bool = False


class OpenItem(BaseModel):
    """A piece of work or context that remains explicitly open until resolved."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=240)
    status: OpenItemStatus = OpenItemStatus.NOT_STARTED
    assignee: str | None = Field(default=None, max_length=120)
    requested_role: Literal["operator", "process_expert", "equipment_expert"]
    due_at: str | None = None
    hold_reason: str = Field(default="", max_length=2000)
    # Optional only while reading legacy Case JSON written before schema v3.
    run_id: str | None = Field(default=None, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    completion_note: str = Field(default="", max_length=2000)
    created_at: str
    updated_at: str


class HypothesisTrack(BaseModel):
    """Human assessment history for a candidate; never a physical-cause claim."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    run_id: str = Field(min_length=1, max_length=80)
    candidate_signal: str = Field(min_length=1, max_length=120)
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    opposing_evidence_ids: list[str] = Field(default_factory=list)
    judgment: HypothesisJudgment = HypothesisJudgment.UNREVIEWED
    change_reason: str = Field(default="", max_length=2000)
    updated_by: str | None = Field(default=None, max_length=120)
    updated_at: str


class HandoverFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    severity: HandoverFindingSeverity
    message: str = Field(min_length=1, max_length=500)
    entity_id: str | None = Field(default=None, max_length=120)


class HandoverSnapshot(BaseModel):
    """Canonical, immutable view of one Case version for handover."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    case_id: str = Field(min_length=1, max_length=80)
    source_case_version: int = Field(ge=0)
    snapshot_hash: str = Field(min_length=1, max_length=128)
    current_run_id: str | None = None
    hypothesis_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    open_item_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)
    findings: list[HandoverFinding] = Field(default_factory=list)
    created_at: str


class Handover(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    sender: str = Field(min_length=1, max_length=120)
    receiver: str = Field(min_length=1, max_length=120)
    source_case_version: int = Field(ge=0)
    snapshot_id: str = Field(min_length=1, max_length=80)
    status: HandoverStatus = HandoverStatus.PUBLISHED
    exception_reason: str = Field(default="", max_length=2000)
    exception_approved_by: str | None = Field(default=None, max_length=120)
    exception_approved_role: str | None = Field(default=None, max_length=80)
    change_request: str = Field(default="", max_length=2000)
    created_at: str
    published_at: str
    accepted_at: str | None = None
    accepted_by: str | None = None
    change_requested_at: str | None = None


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
        "observation_recorded",
        "analysis_run_added",
        "open_item_updated",
        "hypothesis_assessed",
        "handover_linted",
        "handover_published",
        "handover_accepted",
        "handover_changes_requested",
        "handover_superseded",
    ]
    detail: str = Field(min_length=1, max_length=2000)
    actor: Literal["case_orchestrator", "expert", "operator", "analyst", "system"]
    actor_id: str | None = Field(default=None, max_length=120)
    actor_role: ActorRole | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    trace_steps: list[int] = Field(default_factory=list)
    created_at: str


class CaseReviewDecision(BaseModel):
    """Final human decision for a case whose required evidence work is done."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)
    reviewer: str = Field(min_length=1, max_length=120)
    expected_version: int | None = Field(default=None, ge=0)


class StoredCaseReview(CaseReviewDecision):
    reviewed_at: str


class InvestigationCase(BaseModel):
    """A case binds immutable deterministic runs to human follow-up."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    incident_id: str
    dataset: DatasetName
    # Legacy pointer retained for old clients and old persisted JSON.
    investigation_id: str
    status: CaseStatus
    version: int = Field(default=0, ge=0)
    schema_version: int = Field(default=3, ge=1)
    current_run_id: str | None = Field(default=None, max_length=80)
    analysis_runs: list[AnalysisRun] = Field(default_factory=list)
    observations: list[OperatorObservation] = Field(default_factory=list)
    open_items: list[OpenItem] = Field(default_factory=list)
    hypotheses: list[HypothesisTrack] = Field(default_factory=list)
    handover_snapshots: list[HandoverSnapshot] = Field(default_factory=list)
    handovers: list[Handover] = Field(default_factory=list)
    current_handover_id: str | None = Field(default=None, max_length=80)
    next_action: str = Field(min_length=1, max_length=2000)
    tasks: list[EvidenceTask] = Field(default_factory=list)
    events: list[CaseEvent] = Field(default_factory=list)
    reviews: list[StoredCaseReview] = Field(default_factory=list)
    created_at: str
    updated_at: str
