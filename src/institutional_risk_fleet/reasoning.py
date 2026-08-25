"""Typed reasoning-provider contract and credential-free offline implementation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from institutional_risk_fleet.domain import (
    ClaimType,
    EventType,
    FindingSeverity,
    ModelCallRecord,
    Role,
)


class ReasoningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimProposal(ReasoningModel):
    proposal_id: str
    claim_type: ClaimType
    text: str
    material: bool = True
    metric: str | None = None
    value: float | str | None = None
    unit: str | None = None
    period: str | None = None
    evidence_ids: tuple[str, ...] = ()
    tool_execution_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class CreditAnalysis(ReasoningModel):
    summary: str
    hypotheses: tuple[str, ...]
    claims: tuple[ClaimProposal, ...]
    evidence_ids: tuple[str, ...]
    requested_tool_result_ids: tuple[str, ...]
    uncertainties: tuple[str, ...]
    missing_information: tuple[str, ...]


class MarketAnalysis(ReasoningModel):
    summary: str
    assessment: str
    hypotheses: tuple[str, ...]
    claims: tuple[ClaimProposal, ...]
    evidence_ids: tuple[str, ...]
    requested_tool_result_ids: tuple[str, ...]
    uncertainties: tuple[str, ...]
    missing_information: tuple[str, ...]


class InvestigationSynthesis(ReasoningModel):
    primary_hypothesis: str
    alternative_hypotheses: tuple[str, ...]
    material_claims: tuple[ClaimProposal, ...]
    recommendation: str
    recommendation_premise_proposal_ids: tuple[str, ...]
    portfolio_implication: str
    invalidation_conditions: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    unresolved_questions: tuple[str, ...]


class ChallengeCandidate(ReasoningModel):
    target_proposal_id: str
    challenge_type: str
    severity: FindingSeverity
    rationale: str
    conflicting_evidence_ids: tuple[str, ...] = ()
    requested_check: str


class ChallengeOutput(ReasoningModel):
    summary: str
    candidates: tuple[ChallengeCandidate, ...]


class ReasoningBundle(ReasoningModel):
    credit: CreditAnalysis
    market: MarketAnalysis
    investigation: InvestigationSynthesis
    challenger: ChallengeOutput


class ReasoningContext(ReasoningModel):
    investigation_id: str
    scenario_id: str
    scenario_version: str
    event: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    tool_results: tuple[dict[str, Any], ...]


class ProviderOutcome(ReasoningModel):
    bundle: ReasoningBundle
    provider: str
    model_id: str | None = None
    model_calls: tuple[ModelCallRecord, ...] = ()
    fallback_used: bool = False


ModelObserver = Callable[[EventType, Role, str | None, dict[str, Any]], None]


class ReasoningProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model_id(self) -> str | None: ...

    def run(
        self, context: ReasoningContext, observer: ModelObserver | None = None
    ) -> ProviderOutcome: ...


class ReasoningProviderError(RuntimeError):
    """A bounded provider attempt failed without an approved fallback result."""


class ReasoningOutputError(ValueError):
    """Typed output was invalid or referenced non-existent canonical artifacts."""


class OfflineReasoningProvider:
    """Approved deterministic reasoning path; never reads credentials or calls a model."""

    name = "offline"
    model_id = None

    def run(
        self, context: ReasoningContext, observer: ModelObserver | None = None
    ) -> ProviderOutcome:
        tool_by_name = {item["tool_name"]: item for item in context.tool_results}
        leverage_id = str(tool_by_name["leverage_ratio"]["id"])
        spread_id = str(tool_by_name["spread_move"]["id"])
        pnl_id = str(tool_by_name["duration_spread_pnl"]["id"])
        credit_claim = ClaimProposal(
            proposal_id="credit-leverage",
            claim_type=ClaimType.FACTUAL,
            text="Acme FY2025 gross leverage is 4.1x.",
            metric="fy2025_leverage",
            value=4.1,
            unit="x",
            period="FY2025",
            evidence_ids=("evidence-upstream-001",),
            confidence=0.72,
        )
        market_claim = ClaimProposal(
            proposal_id="market-spread",
            claim_type=ClaimType.CALCULATED,
            text="Acme spread widened by 90bp.",
            metric="spread_move",
            value=90.0,
            unit="bps",
            period="2026-01-15",
            evidence_ids=("evidence-market-001",),
            tool_execution_ids=(spread_id,),
            confidence=1.0,
        )
        pnl_claim = ClaimProposal(
            proposal_id="investigator-pnl",
            claim_type=ClaimType.CALCULATED,
            text="The +90bp shock implies approximately -$2.835m of first-order spread P&L.",
            metric="spread_pnl",
            value=-2_835_000.0,
            unit="USD",
            period="risk-event-acme-001",
            tool_execution_ids=(pnl_id,),
            confidence=1.0,
        )
        bundle = ReasoningBundle(
            credit=CreditAnalysis(
                summary="Upstream credit data reports 4.1x leverage.",
                hypotheses=("Reported leverage indicates elevated credit risk.",),
                claims=(credit_claim,),
                evidence_ids=("evidence-upstream-001", "evidence-filing-001"),
                requested_tool_result_ids=(leverage_id,),
                uncertainties=("Upstream and filing leverage values conflict.",),
                missing_information=(),
            ),
            market=MarketAnalysis(
                summary="Acme widened 90bp.",
                assessment="The move is material relative to recent observations.",
                hypotheses=(
                    "The move contains an issuer-specific component.",
                    "Sector repricing and liquidity may also contribute.",
                ),
                claims=(market_claim,),
                evidence_ids=("evidence-market-001",),
                requested_tool_result_ids=(spread_id,),
                uncertainties=("Issuer-specific and sector effects are not fully separated.",),
                missing_information=(),
            ),
            investigation=InvestigationSynthesis(
                primary_hypothesis="The spread widening reflects issuer-specific credit deterioration.",
                alternative_hypotheses=(
                    "The move is partly a broad sector repricing.",
                    "Liquidity pressure amplified the observed spread move.",
                ),
                material_claims=(pnl_claim,),
                recommendation="Escalate Acme for human risk review; do not execute trades.",
                recommendation_premise_proposal_ids=(
                    "credit-leverage",
                    "market-spread",
                    "investigator-pnl",
                ),
                portfolio_implication="The synthetic position has material spread-loss exposure.",
                invalidation_conditions=("Authoritative leverage and market data negate the thesis.",),
                confidence=0.72,
                unresolved_questions=("Upstream and filing leverage values conflict.",),
            ),
            challenger=ChallengeOutput(
                summary="The leverage conflict must be resolved by deterministic verification.",
                candidates=(
                    ChallengeCandidate(
                        target_proposal_id="credit-leverage",
                        challenge_type="source_conflict",
                        severity=FindingSeverity.CRITICAL,
                        rationale="The upstream 4.1x value conflicts with authoritative filing support.",
                        conflicting_evidence_ids=("evidence-filing-001",),
                        requested_check="Recalculate leverage from the filing through the gateway.",
                    ),
                ),
            ),
        )
        return ProviderOutcome(bundle=bundle, provider=self.name)
