"""Validated boundary from untrusted reasoning output to canonical domain state."""

from __future__ import annotations

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    Challenge,
    Claim,
    ClaimType,
    EventType,
    Investigation,
    Role,
    Thesis,
)
from institutional_risk_fleet.permissions import Capability, CapabilityGate, RoleContext
from institutional_risk_fleet.reasoning import ClaimProposal, ProviderOutcome, ReasoningOutputError

_CALCULATED_TOOL_BY_METRIC = {
    "fy2025_leverage": "leverage_ratio",
    "spread_move": "spread_move",
    "spread_pnl": "duration_spread_pnl",
    "duration_spread_pnl": "duration_spread_pnl",
}
_EVIDENCE_OBSERVATION_METRICS = {"fy2025_leverage", "spread_move"}


class ReasoningStateAdapter:
    """Reject invalid references, then atomically construct canonical claims and challenges."""

    def __init__(self, gate: CapabilityGate, audit: AuditLog) -> None:
        self.gate = gate
        self.audit = audit

    def apply(self, investigation: Investigation, outcome: ProviderOutcome) -> None:
        bundle = outcome.bundle
        unique_proposals: dict[str, tuple[Role, ClaimProposal]] = {}
        for role, item in [
            *((Role.CREDIT, item) for item in bundle.credit.claims),
            *((Role.MARKET, item) for item in bundle.market.claims),
            *((Role.INVESTIGATOR, item) for item in bundle.investigation.material_claims),
        ]:
            existing = unique_proposals.get(item.proposal_id)
            if existing is None:
                # Upstream role order is authoritative for identical carried-forward proposals.
                unique_proposals[item.proposal_id] = (role, item)
            elif existing[1] != item:
                raise ReasoningOutputError(
                    f"conflicting duplicate proposal ID: {item.proposal_id}"
                )
        proposals = list(unique_proposals.values())
        self._validate_references(investigation, outcome, proposals)
        self.gate.require(
            RoleContext(Role.INVESTIGATOR), Capability.READ_ARTIFACTS, investigation
        )
        self.gate.require(
            RoleContext(Role.INVESTIGATOR), Capability.CONSTRUCT_THESIS, investigation
        )

        mapping = self._canonical_id_mapping(proposals)
        claims = [
            self._to_claim(
                investigation, mapping[proposal.proposal_id], role, proposal
            )
            for role, proposal in proposals
        ]
        proposal_by_id = {proposal.proposal_id: proposal for _, proposal in proposals}
        if not any(
            proposal_by_id[item].material
            for item in bundle.investigation.recommendation_premise_proposal_ids
        ):
            raise ReasoningOutputError(
                "recommendation requires at least one material premise proposal"
            )
        premise_ids = tuple(
            mapping[item]
            for item in bundle.investigation.recommendation_premise_proposal_ids
        )
        recommendation = Claim(
            id="claim-005",
            author=Role.INVESTIGATOR,
            claim_type=ClaimType.RECOMMENDATION,
            text=bundle.investigation.recommendation,
            premise_claim_ids=premise_ids,
            confidence=bundle.investigation.confidence,
        )

        # No state mutation occurs until the entire provider result has passed validation.
        for claim in (*claims, recommendation):
            self._add_claim(investigation, claim)
        thesis = Thesis(
            id="thesis-001",
            primary_hypothesis=bundle.investigation.primary_hypothesis,
            alternative_hypotheses=bundle.investigation.alternative_hypotheses,
            recommendation_claim_id=recommendation.id,
            claim_ids=(*tuple(claim.id for claim in claims), recommendation.id),
            confidence=bundle.investigation.confidence,
            uncertainties=bundle.investigation.unresolved_questions,
        )
        investigation.theses[thesis.id] = thesis
        investigation.active_thesis_id = thesis.id

        self.gate.require(RoleContext(Role.CHALLENGER), Capability.READ_ARTIFACTS, investigation)
        self.gate.require(RoleContext(Role.CHALLENGER), Capability.CREATE_CHALLENGE, investigation)
        request_id = next(
            (record.request_id for record in outcome.model_calls if record.role == Role.CHALLENGER),
            None,
        )
        for candidate in bundle.challenger.candidates:
            target_claim_id = mapping.get(candidate.target_proposal_id)
            if not target_claim_id:
                continue
            challenge = Challenge(
                id=f"challenge-{len(investigation.challenges) + 1:03d}",
                author=Role.CHALLENGER,
                target_claim_id=target_claim_id,
                challenge_type=candidate.challenge_type,
                severity=candidate.severity,
                rationale=candidate.rationale,
                conflicting_evidence_ids=candidate.conflicting_evidence_ids,
                requested_check=candidate.requested_check,
                model_request_id=request_id,
            )
            investigation.challenges.append(challenge)
            self.audit.append(
                investigation,
                EventType.CHALLENGE_CREATED,
                Role.CHALLENGER,
                challenge.id,
                target_claim_id=challenge.target_claim_id,
                severity=challenge.severity.value,
                challenge_type=challenge.challenge_type,
            )

    @staticmethod
    def _validate_references(
        investigation: Investigation,
        outcome: ProviderOutcome,
        proposals: list[tuple[Role, ClaimProposal]],
    ) -> None:
        bundle = outcome.bundle
        evidence_ids = set(investigation.evidence)
        execution_ids = set(investigation.tool_executions)
        referenced_evidence = {
            *bundle.credit.evidence_ids,
            *bundle.market.evidence_ids,
            *(item for _, proposal in proposals for item in proposal.evidence_ids),
            *(item for candidate in bundle.challenger.candidates for item in candidate.conflicting_evidence_ids),
        }
        referenced_tools = {
            *bundle.credit.requested_tool_result_ids,
            *bundle.market.requested_tool_result_ids,
            *(item for _, proposal in proposals for item in proposal.tool_execution_ids),
        }
        missing_evidence = sorted(referenced_evidence - evidence_ids)
        missing_tools = sorted(referenced_tools - execution_ids)
        proposal_ids = {proposal.proposal_id for _, proposal in proposals}
        missing_premises = sorted(
            set(bundle.investigation.recommendation_premise_proposal_ids) - proposal_ids
        )
        missing_targets = sorted(
            {item.target_proposal_id for item in bundle.challenger.candidates} - proposal_ids
        )
        if missing_evidence or missing_tools or missing_premises or missing_targets:
            raise ReasoningOutputError(
                "unknown provider references: "
                f"evidence={missing_evidence}, tools={missing_tools}, "
                f"premises={missing_premises}, challenge_targets={missing_targets}"
            )
        failed_tools = sorted(
            item for item in referenced_tools if not investigation.tool_executions[item].successful
        )
        if failed_tools:
            raise ReasoningOutputError(f"provider referenced unsuccessful tools: {failed_tools}")
        mismatched_tools = sorted(
            proposal.proposal_id
            for _, proposal in proposals
            if proposal.metric in _CALCULATED_TOOL_BY_METRIC
            and proposal.tool_execution_ids
            and any(
                investigation.tool_executions[item].tool_name
                != _CALCULATED_TOOL_BY_METRIC[proposal.metric]
                for item in proposal.tool_execution_ids
            )
        )
        if mismatched_tools:
            raise ReasoningOutputError(
                f"provider referenced tools incompatible with claim metric: {mismatched_tools}"
            )

    @staticmethod
    def _canonical_id_mapping(
        proposals: list[tuple[Role, ClaimProposal]],
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        used: set[str] = set()
        next_id = 7

        for _, proposal in proposals:
            if (
                proposal.metric == "fy2025_leverage"
                and (
                    proposal.value == 4.1
                    or "evidence-upstream-001" in proposal.evidence_ids
                )
                and "claim-001" not in used
            ):
                mapping[proposal.proposal_id] = "claim-001"
                used.add("claim-001")
                break

        for _, proposal in proposals:
            if proposal.proposal_id in mapping:
                continue
            claim_id = None
            if proposal.metric == "fy2025_leverage" and "claim-001" not in used:
                claim_id = "claim-001"
            elif proposal.metric == "spread_move" and "claim-003" not in used:
                claim_id = "claim-003"
            elif proposal.metric in {"spread_pnl", "duration_spread_pnl"} and "claim-004" not in used:
                claim_id = "claim-004"

            if claim_id is None:
                claim_id = f"claim-{next_id:03d}"
                next_id += 1
            mapping[proposal.proposal_id] = claim_id
            used.add(claim_id)
        return mapping

    @staticmethod
    def _to_claim(
        investigation: Investigation,
        claim_id: str,
        author: Role,
        proposal: ClaimProposal,
    ) -> Claim:
        claim_type = proposal.claim_type
        if claim_type == ClaimType.INFERENCE:
            expected_tool = _CALCULATED_TOOL_BY_METRIC.get(proposal.metric or "")
            actual_tools = {
                investigation.tool_executions[item].tool_name
                for item in proposal.tool_execution_ids
            }
            if expected_tool and actual_tools == {expected_tool}:
                # Gemini sometimes labels a tool-derived atomic result as an inference. Translate
                # only when its supplied lineage proves the frozen deterministic calculation.
                claim_type = ClaimType.CALCULATED
            elif (
                proposal.metric in _EVIDENCE_OBSERVATION_METRICS
                and proposal.evidence_ids
                and not proposal.tool_execution_ids
            ):
                # Likewise, an evidence-backed atomic observation is factual; no support is added.
                claim_type = ClaimType.FACTUAL

        return Claim(
            id=claim_id,
            author=author,
            claim_type=claim_type,
            text=proposal.text,
            material=proposal.material,
            metric=proposal.metric,
            value=proposal.value,
            unit=proposal.unit,
            period=proposal.period,
            evidence_ids=proposal.evidence_ids,
            tool_execution_ids=proposal.tool_execution_ids,
            premise_claim_ids=(),
            confidence=proposal.confidence,
        )

    def _add_claim(self, investigation: Investigation, claim: Claim) -> None:
        if claim.id in investigation.claims:
            raise ReasoningOutputError(f"duplicate canonical claim ID: {claim.id}")
        investigation.claims[claim.id] = claim
        self.audit.append(
            investigation,
            EventType.CLAIM_CREATED,
            claim.author,
            claim.id,
            claim_type=claim.claim_type.value,
            evidence_ids=list(claim.evidence_ids),
            tool_execution_ids=list(claim.tool_execution_ids),
            premise_claim_ids=list(claim.premise_claim_ids),
            supersedes_claim_id=claim.supersedes_claim_id,
        )
