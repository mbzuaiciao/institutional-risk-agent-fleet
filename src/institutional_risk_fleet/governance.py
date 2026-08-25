"""Deterministic machine-clearance and escalation policy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    ClaimStatus,
    ClaimType,
    EventType,
    FindingResult,
    FindingSeverity,
    GovernanceDecision,
    GovernanceStatus,
    HumanReviewStatus,
    Investigation,
    RiskClassification,
    Role,
    Severity,
    VerificationFinding,
)
from institutional_risk_fleet.verification import active_claims


class GovernancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    human_review_exposure_usd: float = Field(default=50_000_000, gt=0)
    maximum_revisions: int = Field(default=1, ge=0)


class GovernanceEngine:
    def __init__(self, audit: AuditLog, policy: GovernancePolicy | None = None) -> None:
        self.audit = audit
        self.policy = policy or GovernancePolicy()

    def evaluate(
        self,
        investigation: Investigation,
        verification_round: int,
        findings: tuple[VerificationFinding, ...],
    ) -> GovernanceDecision:
        rules: list[str] = []
        critical_failures = [
            finding
            for finding in findings
            if finding.result == FindingResult.FAILED
            and finding.severity == FindingSeverity.CRITICAL
        ]
        recommendation_failures = [
            claim.id
            for claim in active_claims(investigation)
            if claim.claim_type == ClaimType.RECOMMENDATION
            and claim.status != ClaimStatus.VERIFIED
        ]
        missing_references = self._missing_references(investigation)
        machine_passed = not critical_failures and not recommendation_failures and not missing_references
        if critical_failures:
            rules.append("unresolved_critical_verification_failure")
        if recommendation_failures:
            rules.append("recommendation_has_unverified_premises")
        if missing_references:
            rules.append("referenced_object_missing")

        risk = self._risk_classification(investigation)
        human_required = (
            investigation.event.severity == Severity.HIGH
            or investigation.event.portfolio_exposure_usd
            >= self.policy.human_review_exposure_usd
        )
        if investigation.event.severity == Severity.HIGH:
            rules.append("high_severity_requires_human_review")
        if investigation.event.portfolio_exposure_usd >= self.policy.human_review_exposure_usd:
            rules.append("material_exposure_requires_human_review")

        if not machine_passed and investigation.revision_count < self.policy.maximum_revisions:
            status = GovernanceStatus.REVISION_REQUIRED
            human_required = False
        elif not machine_passed:
            status = GovernanceStatus.HUMAN_REVIEW_REQUIRED
            human_required = True
            rules.append("revision_limit_reached")
        elif human_required:
            status = GovernanceStatus.HUMAN_REVIEW_REQUIRED
        else:
            status = GovernanceStatus.READY

        decision = GovernanceDecision(
            id=f"governance-{len(investigation.governance_decisions) + 1:03d}",
            verification_round=verification_round,
            status=status,
            machine_verification_passed=machine_passed,
            risk_classification=risk,
            human_review_required=human_required,
            triggered_rules=tuple(dict.fromkeys(rules)),
        )
        investigation.governance_decisions.append(decision)
        investigation.governance_status = status
        investigation.risk_classification = risk
        investigation.human_review_status = (
            HumanReviewStatus.REQUIRED if human_required else HumanReviewStatus.NOT_REQUIRED
        )
        self.audit.append(
            investigation,
            EventType.GOVERNANCE_EVALUATED,
            Role.ORCHESTRATOR,
            decision.id,
            status=status.value,
            machine_verification_passed=machine_passed,
            risk_classification=risk.value,
            human_review_required=human_required,
            triggered_rules=list(decision.triggered_rules),
        )
        if human_required:
            self.audit.append(
                investigation,
                EventType.HUMAN_REVIEW_REQUIRED,
                Role.ORCHESTRATOR,
                decision.id,
                reason="; ".join(decision.triggered_rules),
            )
        return decision

    def escalate_operational_failure(
        self, investigation: Investigation, *, reason: str
    ) -> GovernanceDecision:
        """Create an authoritative governance record when verification cannot safely run."""
        decision = GovernanceDecision(
            id=f"governance-{len(investigation.governance_decisions) + 1:03d}",
            verification_round=0,
            status=GovernanceStatus.HUMAN_REVIEW_REQUIRED,
            machine_verification_passed=False,
            risk_classification=self._risk_classification(investigation),
            human_review_required=True,
            triggered_rules=(reason,),
        )
        investigation.governance_decisions.append(decision)
        investigation.governance_status = decision.status
        investigation.risk_classification = decision.risk_classification
        investigation.human_review_status = HumanReviewStatus.REQUIRED
        self.audit.append(
            investigation,
            EventType.GOVERNANCE_EVALUATED,
            Role.ORCHESTRATOR,
            decision.id,
            status=decision.status.value,
            machine_verification_passed=False,
            risk_classification=decision.risk_classification.value,
            human_review_required=True,
            triggered_rules=[reason],
        )
        self.audit.append(
            investigation,
            EventType.HUMAN_REVIEW_REQUIRED,
            Role.ORCHESTRATOR,
            decision.id,
            reason=reason,
        )
        return decision

    @staticmethod
    def _missing_references(investigation: Investigation) -> tuple[str, ...]:
        missing: list[str] = []
        for claim in active_claims(investigation):
            missing.extend(
                item for item in claim.evidence_ids if item not in investigation.evidence
            )
            missing.extend(
                item for item in claim.tool_execution_ids if item not in investigation.tool_executions
            )
            missing.extend(
                item for item in claim.premise_claim_ids if item not in investigation.claims
            )
        return tuple(sorted(set(missing)))

    def _risk_classification(self, investigation: Investigation) -> RiskClassification:
        if (
            investigation.event.severity == Severity.HIGH
            or investigation.event.portfolio_exposure_usd
            >= self.policy.human_review_exposure_usd
        ):
            return RiskClassification.RED
        if investigation.event.severity == Severity.MEDIUM:
            return RiskClassification.YELLOW
        return RiskClassification.GREEN
