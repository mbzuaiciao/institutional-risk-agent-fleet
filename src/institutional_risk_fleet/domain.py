"""Typed domain objects for the deterministic institutional-risk workflow."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Role(StrEnum):
    ORCHESTRATOR = "orchestrator"
    CREDIT = "credit_agent"
    MARKET = "market_agent"
    EVIDENCE = "evidence_service"
    INVESTIGATOR = "investigator"
    CHALLENGER = "challenger"
    VERIFIER = "verifier"
    HUMAN = "human_reviewer"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LifecycleStatus(StrEnum):
    CREATED = "CREATED"
    INVESTIGATING = "INVESTIGATING"
    VERIFYING = "VERIFYING"
    REVISING = "REVISING"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    COMPLETED = "COMPLETED"


class GovernanceStatus(StrEnum):
    PENDING = "PENDING"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    READY = "READY"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class RiskClassification(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class HumanReviewStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MORE_INVESTIGATION = "MORE_INVESTIGATION"


class HumanAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MORE_INVESTIGATION = "REQUEST_MORE_INVESTIGATION"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


class ClaimType(StrEnum):
    FACTUAL = "FACTUAL"
    CALCULATED = "CALCULATED"
    INFERENCE = "INFERENCE"
    RECOMMENDATION = "RECOMMENDATION"


class ClaimStatus(StrEnum):
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"


class FindingResult(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class EventType(StrEnum):
    RISK_EVENT_RECEIVED = "risk_event_received"
    INVESTIGATION_STARTED = "investigation_started"
    LIFECYCLE_TRANSITIONED = "lifecycle_transitioned"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TOOL_REQUESTED = "tool_requested"
    PERMISSION_DENIED = "permission_denied"
    TOOL_EXECUTED = "tool_executed"
    TOOL_FAILED = "tool_failed"
    EVIDENCE_ADDED = "evidence_added"
    CLAIM_CREATED = "claim_created"
    CHALLENGE_CREATED = "challenge_created"
    MODEL_REQUEST_STARTED = "model_request_started"
    MODEL_RESPONSE_RECEIVED = "model_response_received"
    MODEL_OUTPUT_VALIDATION_FAILED = "model_output_validation_failed"
    MODEL_RETRY = "model_retry"
    MODEL_PROVIDER_FAILED = "model_provider_failed"
    MODEL_FALLBACK_USED = "model_fallback_used"
    MODEL_ROLE_COMPLETED = "model_role_completed"
    VERIFICATION_FAILED = "verification_failed"
    CLAIM_REVISED = "claim_revised"
    VERIFICATION_PASSED = "verification_passed"
    GOVERNANCE_EVALUATED = "governance_evaluated"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HUMAN_DECISION = "human_decision"
    HUMAN_DECISION_REJECTED = "human_decision_rejected"
    INVESTIGATION_COMPLETED = "investigation_completed"


class RiskEvent(FrozenModel):
    id: str
    issuer_id: str
    issuer_name: str
    portfolio_exposure_usd: float = Field(gt=0)
    previous_spread_bps: float = Field(ge=0)
    current_spread_bps: float = Field(ge=0)
    spread_move_bps: float
    severity: Severity
    occurred_at: datetime
    synthetic: bool = True

    @model_validator(mode="after")
    def validate_spread_move(self) -> RiskEvent:
        expected = self.current_spread_bps - self.previous_spread_bps
        if abs(self.spread_move_bps - expected) > 1e-9:
            raise ValueError("spread_move_bps must equal current spread minus previous spread")
        if not self.synthetic:
            raise ValueError("Milestones 0-2 accept synthetic events only")
        return self


class Task(FrozenModel):
    id: str
    role: Role
    objective: str
    status: TaskStatus = TaskStatus.PENDING


class NormalizedFact(FrozenModel):
    metric: str
    value: float | str
    unit: str
    period: str | None = None


class Evidence(FrozenModel):
    id: str
    source_type: str
    title: str
    locator: str
    content: str
    authoritative: bool = False
    synthetic: bool = True
    facts: dict[str, NormalizedFact] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_synthetic(self) -> Evidence:
        if not self.synthetic:
            raise ValueError("Milestones 0-2 accept synthetic evidence only")
        return self


class ToolExecution(FrozenModel):
    id: str
    tool_name: str
    tool_version: str
    actor: Role
    inputs: dict[str, Any]
    output: float | str | dict[str, float] | None
    units: str | None
    successful: bool
    provenance: str
    error: str | None = None


class Claim(FrozenModel):
    id: str
    author: Role
    claim_type: ClaimType
    text: str
    material: bool = True
    metric: str | None = None
    value: float | str | None = None
    unit: str | None = None
    period: str | None = None
    evidence_ids: tuple[str, ...] = ()
    tool_execution_ids: tuple[str, ...] = ()
    premise_claim_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    status: ClaimStatus = ClaimStatus.ADOPTED
    supersedes_claim_id: str | None = None

    @model_validator(mode="after")
    def enforce_lineage(self) -> Claim:
        if self.material and self.claim_type == ClaimType.FACTUAL and not self.evidence_ids:
            raise ValueError("material factual claims require evidence lineage")
        if self.claim_type == ClaimType.CALCULATED and not self.tool_execution_ids:
            raise ValueError("calculated claims require successful tool lineage")
        if self.claim_type in {ClaimType.INFERENCE, ClaimType.RECOMMENDATION} and not self.premise_claim_ids:
            raise ValueError("inference and recommendation claims require premise claims")
        numeric = isinstance(self.value, (int, float)) and not isinstance(self.value, bool)
        if self.material and numeric and (not self.metric or not self.unit or not self.period):
            raise ValueError("material numeric claims require metric, unit, and period")
        return self


class Thesis(FrozenModel):
    id: str
    primary_hypothesis: str
    alternative_hypotheses: tuple[str, ...]
    recommendation_claim_id: str
    claim_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    uncertainties: tuple[str, ...]
    supersedes_thesis_id: str | None = None


class Challenge(FrozenModel):
    id: str
    author: Role
    target_claim_id: str
    challenge_type: str
    severity: FindingSeverity
    rationale: str
    conflicting_evidence_ids: tuple[str, ...] = ()
    requested_check: str
    model_request_id: str | None = None

    @model_validator(mode="after")
    def require_challenger_author(self) -> Challenge:
        if self.author != Role.CHALLENGER:
            raise ValueError("challenges must be authored by the Challenger")
        return self


class ModelCallRecord(FrozenModel):
    id: str
    role: Role
    provider: str
    model_id: str
    prompt_version: str
    request_id: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float = Field(ge=0)
    validation_status: str
    retry_count: int = Field(default=0, ge=0)
    fallback_used: bool = False
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_type: str | None = None


class VerificationFinding(FrozenModel):
    id: str
    verification_round: int = Field(ge=1)
    target_claim_id: str
    check_type: str
    severity: FindingSeverity
    result: FindingResult
    observed_value: float | str | None = None
    expected_value: float | str | None = None
    units: str | None = None
    rationale: str


class GovernanceDecision(FrozenModel):
    id: str
    verification_round: int
    status: GovernanceStatus
    machine_verification_passed: bool
    risk_classification: RiskClassification
    human_review_required: bool
    triggered_rules: tuple[str, ...]


class HumanDecision(FrozenModel):
    id: str
    action: HumanAction
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class AuditEvent(FrozenModel):
    sequence: int = Field(ge=1)
    id: str
    investigation_id: str
    actor: Role
    event_type: EventType
    related_object_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class Investigation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    event: RiskEvent
    lifecycle_status: LifecycleStatus = LifecycleStatus.CREATED
    governance_status: GovernanceStatus = GovernanceStatus.PENDING
    risk_classification: RiskClassification = RiskClassification.RED
    human_review_status: HumanReviewStatus = HumanReviewStatus.NOT_REQUIRED
    revision_count: int = Field(default=0, ge=0)
    reasoning_provider: str = "offline"
    configured_model_id: str | None = None
    tasks: dict[str, Task] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    tool_executions: dict[str, ToolExecution] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)
    theses: dict[str, Thesis] = Field(default_factory=dict)
    challenges: list[Challenge] = Field(default_factory=list)
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    active_thesis_id: str | None = None
    verification_findings: list[VerificationFinding] = Field(default_factory=list)
    governance_decisions: list[GovernanceDecision] = Field(default_factory=list)
    human_decisions: list[HumanDecision] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
