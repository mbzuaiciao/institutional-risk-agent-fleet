"""Structured claim verification; no lexical-overlap heuristics."""

from __future__ import annotations

from collections.abc import Iterable

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    Claim,
    ClaimStatus,
    ClaimType,
    EventType,
    FindingResult,
    FindingSeverity,
    Investigation,
    VerificationFinding,
)
from institutional_risk_fleet.permissions import Capability, CapabilityGate, RoleContext


def active_claims(investigation: Investigation) -> tuple[Claim, ...]:
    superseded = {
        claim.supersedes_claim_id
        for claim in investigation.claims.values()
        if claim.supersedes_claim_id is not None
    }
    claims = [claim for claim in investigation.claims.values() if claim.id not in superseded]
    priority = {
        ClaimType.FACTUAL: 0,
        ClaimType.CALCULATED: 0,
        ClaimType.INFERENCE: 1,
        ClaimType.RECOMMENDATION: 2,
    }
    return tuple(sorted(claims, key=lambda item: (priority[item.claim_type], item.id)))


class StructuredVerifier:
    def __init__(
        self,
        context: RoleContext,
        gate: CapabilityGate,
        audit: AuditLog,
    ) -> None:
        self.context = context
        self.gate = gate
        self.audit = audit

    def verify_round(
        self, investigation: Investigation, verification_round: int
    ) -> tuple[VerificationFinding, ...]:
        self.gate.require(self.context, Capability.READ_ARTIFACTS, investigation)
        self.gate.require(self.context, Capability.CREATE_FINDING, investigation)
        findings: list[VerificationFinding] = []
        for claim in active_claims(investigation):
            finding = self._verify_claim(investigation, claim, verification_round)
            investigation.verification_findings.append(finding)
            findings.append(finding)
            new_status = (
                ClaimStatus.VERIFIED
                if finding.result == FindingResult.PASSED
                else ClaimStatus.REJECTED
            )
            investigation.claims[claim.id] = claim.model_copy(update={"status": new_status})
            self.audit.append(
                investigation,
                EventType.VERIFICATION_PASSED
                if finding.result == FindingResult.PASSED
                else EventType.VERIFICATION_FAILED,
                self.context.role,
                claim.id,
                finding_id=finding.id,
                check_type=finding.check_type,
                observed=finding.observed_value,
                expected=finding.expected_value,
                units=finding.units,
                rationale=finding.rationale,
            )
        return tuple(findings)

    def _verify_claim(
        self, investigation: Investigation, claim: Claim, verification_round: int
    ) -> VerificationFinding:
        missing_evidence = [
            evidence_id
            for evidence_id in claim.evidence_ids
            if evidence_id not in investigation.evidence
        ]
        if missing_evidence:
            return self._finding(
                investigation,
                claim,
                verification_round,
                "evidence_identity",
                FindingResult.FAILED,
                rationale=f"Missing evidence objects: {missing_evidence}",
            )

        tool_executions = []
        for execution_id in claim.tool_execution_ids:
            execution = investigation.tool_executions.get(execution_id)
            if execution is None or not execution.successful:
                return self._finding(
                    investigation,
                    claim,
                    verification_round,
                    "tool_lineage",
                    FindingResult.FAILED,
                    rationale=f"Missing or unsuccessful tool execution: {execution_id}",
                )
            tool_executions.append(execution)

        if claim.claim_type in {ClaimType.INFERENCE, ClaimType.RECOMMENDATION}:
            invalid_premises = [
                premise_id
                for premise_id in claim.premise_claim_ids
                if investigation.claims.get(premise_id) is None
                or investigation.claims[premise_id].status != ClaimStatus.VERIFIED
            ]
            if invalid_premises:
                return self._finding(
                    investigation,
                    claim,
                    verification_round,
                    "premise_status",
                    FindingResult.FAILED,
                    rationale=f"Recommendation/inference depends on unverified claims: {invalid_premises}",
                )
            return self._finding(
                investigation,
                claim,
                verification_round,
                "premise_status",
                FindingResult.PASSED,
                rationale="All material premise claims are verified.",
            )

        if claim.material and claim.claim_type == ClaimType.FACTUAL:
            cited_authoritative = any(
                investigation.evidence[evidence_id].authoritative
                for evidence_id in claim.evidence_ids
            )
            if not cited_authoritative and not isinstance(claim.value, (int, float)):
                return self._finding(
                    investigation,
                    claim,
                    verification_round,
                    "evidence_authority",
                    FindingResult.FAILED,
                    rationale="Retrieval alone does not establish support; no authoritative evidence is cited.",
                )

        if isinstance(claim.value, (int, float)) and not isinstance(claim.value, bool):
            return self._verify_numeric(
                investigation, claim, verification_round, (execution.output for execution in tool_executions)
            )

        return self._finding(
            investigation,
            claim,
            verification_round,
            "lineage",
            FindingResult.PASSED,
            rationale="Required evidence and tool lineage exists.",
        )

    def _verify_numeric(
        self,
        investigation: Investigation,
        claim: Claim,
        verification_round: int,
        tool_outputs: Iterable[float | str | dict[str, float] | None],
    ) -> VerificationFinding:
        expected_values: list[float] = []
        expected_sources: list[str] = []
        unit_conflicts: list[str] = []
        for evidence in investigation.evidence.values():
            if not evidence.authoritative or claim.metric not in evidence.facts:
                continue
            fact = evidence.facts[claim.metric]
            if fact.period == claim.period and isinstance(fact.value, (int, float)):
                expected_values.append(float(fact.value))
                expected_sources.append(evidence.id)
                if fact.unit != claim.unit:
                    unit_conflicts.append(f"{evidence.id}:{fact.unit}")
        for execution_id, output in zip(claim.tool_execution_ids, tool_outputs, strict=True):
            execution = investigation.tool_executions[execution_id]
            if isinstance(output, (int, float)) and not isinstance(output, bool):
                expected_values.append(float(output))
                expected_sources.append(execution_id)
                if execution.units != claim.unit:
                    unit_conflicts.append(f"{execution_id}:{execution.units}")
        if unit_conflicts:
            return self._finding(
                investigation,
                claim,
                verification_round,
                "numeric_units",
                FindingResult.FAILED,
                observed=claim.value,
                units=claim.unit,
                rationale=f"Claim units conflict with support: {unit_conflicts}",
            )
        if not expected_values:
            return self._finding(
                investigation,
                claim,
                verification_round,
                "numeric_lineage",
                FindingResult.FAILED,
                observed=claim.value,
                units=claim.unit,
                rationale="No authoritative numeric fact or successful numeric tool output was found.",
            )
        expected = expected_values[0]
        support_disagrees = any(abs(value - expected) > 1e-9 for value in expected_values[1:])
        observed_value = claim.value
        if not isinstance(observed_value, (int, float)) or isinstance(observed_value, bool):
            raise TypeError("numeric verification received a non-numeric claim value")
        observed = float(observed_value)
        passed = not support_disagrees and abs(observed - expected) <= 1e-9
        rationale = (
            f"Claim matches structured support from {expected_sources}."
            if passed
            else f"Claim value conflicts with structured support from {expected_sources}."
        )
        return self._finding(
            investigation,
            claim,
            verification_round,
            "numeric_consistency",
            FindingResult.PASSED if passed else FindingResult.FAILED,
            observed=observed,
            expected=expected,
            units=claim.unit,
            rationale=rationale,
        )

    @staticmethod
    def _finding(
        investigation: Investigation,
        claim: Claim,
        verification_round: int,
        check_type: str,
        result: FindingResult,
        *,
        observed: float | str | None = None,
        expected: float | str | None = None,
        units: str | None = None,
        rationale: str,
    ) -> VerificationFinding:
        index = len(investigation.verification_findings) + 1
        return VerificationFinding(
            id=f"finding-{index:03d}",
            verification_round=verification_round,
            target_claim_id=claim.id,
            check_type=check_type,
            severity=FindingSeverity.CRITICAL if result == FindingResult.FAILED else FindingSeverity.INFO,
            result=result,
            observed_value=observed,
            expected_value=expected,
            units=units,
            rationale=rationale,
        )
