from __future__ import annotations

from datetime import UTC, datetime

import pytest
from google.adk.agents import ParallelAgent, SequentialAgent
from pydantic import ValidationError

from institutional_risk_fleet.adk_provider import (
    DEFAULT_GEMINI_MODEL,
    GeminiReasoningConfig,
    ProviderAttemptError,
    ResilientReasoningProvider,
    build_adk_pipeline,
)
from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    ClaimType,
    EventType,
    FindingResult,
    ModelCallRecord,
    Role,
)
from institutional_risk_fleet.permissions import (
    Capability,
    CapabilityGate,
    PermissionDenied,
    RoleContext,
)
from institutional_risk_fleet.reasoning import (
    ChallengeCandidate,
    ClaimProposal,
    OfflineReasoningProvider,
    ProviderOutcome,
    ReasoningContext,
)
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


class CorrectedProvider:
    name = "gemini-test"
    model_id = "gemini-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        offline = OfflineReasoningProvider().run(context)
        leverage_id = next(
            str(item["id"])
            for item in context.tool_results
            if item["tool_name"] == "leverage_ratio"
        )
        corrected = offline.bundle.credit.claims[0].model_copy(
            update={
                "claim_type": ClaimType.CALCULATED,
                "text": "Acme FY2025 gross leverage is 3.8x.",
                "value": 3.8,
                "evidence_ids": ("evidence-filing-001",),
                "tool_execution_ids": (leverage_id,),
                "confidence": 1.0,
            }
        )
        bundle = offline.bundle.model_copy(
            update={
                "credit": offline.bundle.credit.model_copy(update={"claims": (corrected,)})
            }
        )
        now = datetime.now(UTC)
        record = ModelCallRecord(
            id="model-call-test-001",
            role=Role.CREDIT,
            provider=self.name,
            model_id=self.model_id,
            prompt_version="credit-v1",
            request_id="request-test-001",
            started_at=now,
            ended_at=now,
            latency_ms=0,
            validation_status="valid",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )
        return ProviderOutcome(
            bundle=bundle,
            provider=self.name,
            model_id=self.model_id,
            model_calls=(record,),
        )


class UnknownReferenceProvider:
    name = "invalid-test"
    model_id = "invalid-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        claim = outcome.bundle.credit.claims[0].model_copy(
            update={"evidence_ids": ("evidence-does-not-exist",)}
        )
        bundle = outcome.bundle.model_copy(
            update={
                "credit": outcome.bundle.credit.model_copy(update={"claims": (claim,)})
            }
        )
        return ProviderOutcome(
            bundle=bundle, provider=self.name, model_id=self.model_id
        )


class UnknownToolProvider:
    name = "invalid-tool-test"
    model_id = "invalid-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        claim = outcome.bundle.market.claims[0].model_copy(
            update={"tool_execution_ids": ("tool-execution-does-not-exist",)}
        )
        bundle = outcome.bundle.model_copy(
            update={
                "market": outcome.bundle.market.model_copy(update={"claims": (claim,)})
            }
        )
        return ProviderOutcome(
            bundle=bundle, provider=self.name, model_id=self.model_id
        )


class SemanticallyMalformedProvider:
    name = "malformed-test"
    model_id = "invalid-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        synthesis = outcome.bundle.investigation.model_copy(
            update={"recommendation_premise_proposal_ids": ()}
        )
        bundle = outcome.bundle.model_copy(update={"investigation": synthesis})
        return ProviderOutcome(
            bundle=bundle, provider=self.name, model_id=self.model_id
        )


class CarriedForwardProposalProvider:
    name = "carried-forward-test"
    model_id = "gemini-test-model"

    def __init__(self, *, conflicting: bool = False) -> None:
        self.conflicting = conflicting

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        carried = outcome.bundle.credit.claims[0]
        if self.conflicting:
            carried = carried.model_copy(update={"text": "Conflicting carried-forward content."})
        synthesis = outcome.bundle.investigation.model_copy(
            update={
                "material_claims": (
                    carried,
                    *outcome.bundle.investigation.material_claims,
                )
            }
        )
        return outcome.model_copy(
            update={
                "bundle": outcome.bundle.model_copy(
                    update={"investigation": synthesis}
                ),
                "provider": self.name,
                "model_id": self.model_id,
            }
        )


class UnsupportedClaimRepairProvider:
    name = "unsupported-repair-test"
    model_id = "gemini-test-model"

    def __init__(self, updates: dict[str, object] | None = None) -> None:
        self.updates = updates or {
            "claim_type": ClaimType.FACTUAL,
            "evidence_ids": (),
            "tool_execution_ids": (),
        }

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        unsupported = outcome.bundle.investigation.material_claims[0].model_copy(
            update=self.updates
        )
        synthesis = outcome.bundle.investigation.model_copy(
            update={"material_claims": (unsupported,)}
        )
        return outcome.model_copy(
            update={"bundle": outcome.bundle.model_copy(update={"investigation": synthesis})}
        )


class ToolDerivedInferenceProvider:
    name = "tool-inference-test"
    model_id = "gemini-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        tool_derived = outcome.bundle.investigation.material_claims[0].model_copy(
            update={"claim_type": ClaimType.INFERENCE}
        )
        synthesis = outcome.bundle.investigation.model_copy(
            update={"material_claims": (tool_derived,)}
        )
        return outcome.model_copy(
            update={"bundle": outcome.bundle.model_copy(update={"investigation": synthesis})}
        )


class NonMaterialRecommendationPremisesProvider:
    name = "nonmaterial-premises-test"
    model_id = "gemini-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        credit = tuple(item.model_copy(update={"material": False}) for item in outcome.bundle.credit.claims)
        market = tuple(item.model_copy(update={"material": False}) for item in outcome.bundle.market.claims)
        synthesis = outcome.bundle.investigation.model_copy(
            update={
                "material_claims": tuple(
                    item.model_copy(update={"material": False})
                    for item in outcome.bundle.investigation.material_claims
                )
            }
        )
        bundle = outcome.bundle.model_copy(
            update={
                "credit": outcome.bundle.credit.model_copy(update={"claims": credit}),
                "market": outcome.bundle.market.model_copy(update={"claims": market}),
                "investigation": synthesis,
            }
        )
        return outcome.model_copy(update={"bundle": bundle})


class MismatchedToolLineageProvider:
    name = "mismatched-tool-test"
    model_id = "gemini-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        outcome = OfflineReasoningProvider().run(context)
        pnl = outcome.bundle.investigation.material_claims[0].model_copy(
            update={"tool_execution_ids": ("tool-execution-003",)}
        )
        synthesis = outcome.bundle.investigation.model_copy(
            update={"material_claims": (pnl,)}
        )
        return outcome.model_copy(
            update={"bundle": outcome.bundle.model_copy(update={"investigation": synthesis})}
        )


class AlwaysFailProvider:
    name = "always-fail"
    model_id = "gemini-test-model"

    def run(self, context: ReasoningContext, observer=None) -> ProviderOutcome:  # type: ignore[no-untyped-def]
        raise ProviderAttemptError("synthetic rate limit", ())


def test_offline_default_needs_no_credentials_and_preserves_seeded_revision(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    investigation = DeterministicRiskWorkflow().run()
    assert investigation.reasoning_provider == "offline"
    assert investigation.configured_model_id is None
    assert investigation.claims["claim-001"].value == 4.1
    assert investigation.claims["claim-002"].value == 3.8
    assert investigation.challenges[0].author == Role.CHALLENGER


def test_gemini_configuration_has_a_real_configurable_model_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiReasoningConfig.from_env().model_id == DEFAULT_GEMINI_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "gemini-configured-test")
    assert GeminiReasoningConfig.from_env().model_id == "gemini-configured-test"


def test_model_cannot_spoof_claim_author() -> None:
    with pytest.raises(ValidationError, match="author"):
        ClaimProposal.model_validate(
            {
                "proposal_id": "spoof",
                "author": "verifier",
                "claim_type": "FACTUAL",
                "text": "Spoofed authority.",
                "confidence": 0.5,
            }
        )


def test_unknown_model_reference_is_rejected_before_canonical_state() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=UnknownReferenceProvider()
    ).run()
    assert not investigation.claims
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"
    assert any(
        event.event_type == EventType.MODEL_OUTPUT_VALIDATION_FAILED
        for event in investigation.audit_events
    )


def test_unknown_tool_reference_is_rejected_before_canonical_state() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=UnknownToolProvider()
    ).run()
    assert not investigation.claims
    assert any(
        event.event_type == EventType.MODEL_OUTPUT_VALIDATION_FAILED
        for event in investigation.audit_events
    )


def test_semantically_malformed_output_is_rejected_before_state() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=SemanticallyMalformedProvider()
    ).run()
    assert not investigation.claims
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"
    assert any(
        event.event_type == EventType.MODEL_OUTPUT_VALIDATION_FAILED
        for event in investigation.audit_events
    )


def test_identical_carried_forward_proposal_keeps_original_author_once() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=CarriedForwardProposalProvider()
    ).run()
    assert investigation.claims["claim-001"].author == Role.CREDIT
    assert "claim-007" not in investigation.claims


def test_conflicting_duplicate_proposal_id_is_rejected_before_state() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=CarriedForwardProposalProvider(conflicting=True)
    ).run()
    assert not investigation.claims
    assert EventType.MODEL_OUTPUT_VALIDATION_FAILED in {
        event.event_type for event in investigation.audit_events
    }


def test_adapter_does_not_downgrade_unsupported_material_claim() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=UnsupportedClaimRepairProvider()
    ).run()
    assert not investigation.claims
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"


@pytest.mark.parametrize(
    "updates",
    (
        {
            "claim_type": ClaimType.CALCULATED,
            "evidence_ids": ("evidence-filing-001",),
            "tool_execution_ids": (),
        },
        {"unit": None},
    ),
)
def test_adapter_does_not_repair_missing_tool_or_numeric_metadata(
    updates: dict[str, object],
) -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=UnsupportedClaimRepairProvider(updates)
    ).run()
    assert not investigation.claims
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"


def test_adapter_narrowly_translates_proven_tool_result_without_adding_lineage() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=ToolDerivedInferenceProvider()
    ).run()
    claim = investigation.claims["claim-004"]
    assert claim.claim_type == ClaimType.CALCULATED
    assert claim.value == -2_835_000.0
    assert claim.tool_execution_ids == ("tool-execution-004",)


def test_recommendation_requires_a_material_premise() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=NonMaterialRecommendationPremisesProvider()
    ).run()
    assert not investigation.claims
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"


def test_metric_cannot_borrow_an_unrelated_successful_tool_execution() -> None:
    investigation = DeterministicRiskWorkflow(
        reasoning_provider=MismatchedToolLineageProvider()
    ).run()
    assert not investigation.claims
    assert EventType.MODEL_OUTPUT_VALIDATION_FAILED in {
        event.event_type for event in investigation.audit_events
    }


def test_honest_first_pass_can_clear_verification_without_forced_revision() -> None:
    workflow = DeterministicRiskWorkflow(reasoning_provider=CorrectedProvider())
    investigation = workflow.run()
    assert investigation.claims["claim-001"].value == 3.8
    assert "claim-002" not in investigation.claims
    assert investigation.revision_count == 0
    finding = next(
        item for item in investigation.verification_findings if item.target_claim_id == "claim-001"
    )
    assert finding.result == FindingResult.PASSED
    assert investigation.model_calls[0].total_tokens == 15
    with pytest.raises(ValueError, match="cannot complete"):
        workflow.complete_investigation(investigation)


def test_challenger_schema_cannot_mark_a_claim_verified() -> None:
    with pytest.raises(ValidationError, match="verified"):
        ChallengeCandidate.model_validate(
            {
                "target_proposal_id": "credit-leverage",
                "challenge_type": "source_conflict",
                "severity": "CRITICAL",
                "rationale": "Conflicting values.",
                "requested_check": "Recalculate.",
                "verified": True,
            }
        )


def test_challenger_cannot_create_verifier_findings_and_denial_is_audited() -> None:
    workflow = DeterministicRiskWorkflow()
    investigation = workflow.run()
    gate = CapabilityGate(AuditLog())
    with pytest.raises(PermissionDenied):
        gate.require(RoleContext(Role.CHALLENGER), Capability.CREATE_FINDING, investigation)
    assert investigation.verification_findings[0].target_claim_id == "claim-001"
    assert investigation.verification_findings[0].result == FindingResult.FAILED
    assert investigation.audit_events[-1].event_type == EventType.PERMISSION_DENIED


def test_bounded_retry_and_explicit_fallback_are_audited() -> None:
    provider = ResilientReasoningProvider(
        AlwaysFailProvider(), max_retries=1, fallback=OfflineReasoningProvider()
    )
    investigation = DeterministicRiskWorkflow(reasoning_provider=provider).run()
    event_types = [event.event_type for event in investigation.audit_events]
    assert event_types.count(EventType.MODEL_PROVIDER_FAILED) == 2
    assert event_types.count(EventType.MODEL_RETRY) == 1
    assert event_types.count(EventType.MODEL_FALLBACK_USED) == 1
    assert investigation.claims["claim-002"].value == 3.8


def test_exhausted_provider_without_fallback_is_governance_escalated() -> None:
    provider = ResilientReasoningProvider(AlwaysFailProvider(), max_retries=0)
    investigation = DeterministicRiskWorkflow(reasoning_provider=provider).run()
    assert not investigation.claims
    assert investigation.governance_decisions[-1].machine_verification_passed is False
    assert investigation.governance_status.value == "HUMAN_REVIEW_REQUIRED"
    assert investigation.human_review_status.value == "REQUIRED"
    assert EventType.MODEL_PROVIDER_FAILED in {
        event.event_type for event in investigation.audit_events
    }


def test_adk_graph_matches_frozen_role_order_and_has_no_model_tools() -> None:
    pipeline = build_adk_pipeline("gemini-test-model")
    assert isinstance(pipeline, SequentialAgent)
    assert isinstance(pipeline.sub_agents[0], ParallelAgent)
    parallel = pipeline.sub_agents[0]
    assert [agent.name for agent in parallel.sub_agents] == [
        Role.CREDIT.value,
        Role.MARKET.value,
    ]
    assert [agent.name for agent in pipeline.sub_agents[1:]] == [
        Role.INVESTIGATOR.value,
        Role.CHALLENGER.value,
    ]
    for agent in (*parallel.sub_agents, *pipeline.sub_agents[1:]):
        assert getattr(agent, "tools", []) == []
        assert getattr(agent, "output_schema", None) is not None
