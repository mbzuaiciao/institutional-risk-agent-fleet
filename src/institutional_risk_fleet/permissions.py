"""Code-enforced capabilities bound to active role contexts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import EventType, Investigation, Role


class Capability(StrEnum):
    CREATE_TASK = "create_task"
    INSPECT_STATUS = "inspect_status"
    ROUTE = "route"
    READ_ISSUER_FINANCIALS = "read_issuer_financials"
    READ_CREDIT_EVIDENCE = "read_credit_evidence"
    READ_MARKET_HISTORY = "read_market_history"
    READ_COMPARABLES = "read_comparables"
    RETRIEVE_EVIDENCE = "retrieve_evidence"
    REGISTER_EVIDENCE = "register_evidence"
    CALL_CREDIT_TOOL = "call_credit_tool"
    CALL_MARKET_TOOL = "call_market_tool"
    CALL_PORTFOLIO_TOOL = "call_portfolio_tool"
    READ_PORTFOLIO_POSITIONS = "read_portfolio_positions"
    READ_ARTIFACTS = "read_artifacts"
    CONSTRUCT_THESIS = "construct_thesis"
    CREATE_CHALLENGE = "create_challenge"
    CREATE_FINDING = "create_finding"
    RECORD_HUMAN_DECISION = "record_human_decision"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.ORCHESTRATOR: frozenset(
        {Capability.CREATE_TASK, Capability.INSPECT_STATUS, Capability.ROUTE}
    ),
    Role.CREDIT: frozenset(
        {
            Capability.READ_ISSUER_FINANCIALS,
            Capability.READ_CREDIT_EVIDENCE,
            Capability.CALL_CREDIT_TOOL,
        }
    ),
    Role.MARKET: frozenset(
        {Capability.READ_MARKET_HISTORY, Capability.READ_COMPARABLES, Capability.CALL_MARKET_TOOL}
    ),
    Role.EVIDENCE: frozenset({Capability.RETRIEVE_EVIDENCE, Capability.REGISTER_EVIDENCE}),
    Role.INVESTIGATOR: frozenset(
        {
            Capability.READ_ARTIFACTS,
            Capability.CONSTRUCT_THESIS,
            Capability.READ_PORTFOLIO_POSITIONS,
            Capability.CALL_PORTFOLIO_TOOL,
        }
    ),
    Role.CHALLENGER: frozenset({Capability.READ_ARTIFACTS, Capability.CREATE_CHALLENGE}),
    Role.VERIFIER: frozenset({Capability.READ_ARTIFACTS, Capability.CREATE_FINDING}),
    Role.HUMAN: frozenset({Capability.RECORD_HUMAN_DECISION}),
}


@dataclass(frozen=True, slots=True)
class RoleContext:
    """Identity assigned by orchestration, never supplied to an individual tool call."""

    role: Role


class PermissionDenied(PermissionError):
    def __init__(self, role: Role, capability: Capability) -> None:
        self.role = role
        self.capability = capability
        super().__init__(f"{role.value} lacks capability {capability.value}")


class CapabilityGate:
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def require(
        self,
        context: RoleContext,
        capability: Capability,
        investigation: Investigation,
        *,
        related_object_id: str | None = None,
    ) -> None:
        if capability in ROLE_CAPABILITIES.get(context.role, frozenset()):
            return
        self.audit.append(
            investigation,
            EventType.PERMISSION_DENIED,
            context.role,
            related_object_id,
            capability=capability.value,
            reason=f"{context.role.value} is not granted {capability.value}",
        )
        raise PermissionDenied(context.role, capability)
