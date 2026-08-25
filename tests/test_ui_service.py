from __future__ import annotations

from pathlib import Path

import pytest

from institutional_risk_fleet.domain import (
    ClaimStatus,
    GovernanceStatus,
    HumanAction,
    HumanReviewStatus,
    LifecycleStatus,
)
from institutional_risk_fleet.ui_service import (
    DecisionInputError,
    DemoApplication,
    GeminiUnavailableError,
    gemini_availability,
)


def test_reset_produces_frozen_initial_scenario() -> None:
    application = DemoApplication()
    application.trigger()
    initial = application.reset()
    assert not application.triggered
    assert application.current_investigation() is None
    assert initial.issuer == "Acme Corp"
    assert initial.exposure_usd == 75_000_000
    assert initial.previous_spread_bps == 120
    assert initial.current_spread_bps == 210
    assert initial.lifecycle == "NOT_TRIGGERED"


def test_trigger_is_idempotent_and_rerender_does_not_duplicate_state() -> None:
    application = DemoApplication()
    first = application.trigger()
    first_audit_count = len(first.audit_events)
    second = application.trigger()
    application.portfolio_view()
    application.investigation_view()
    application.verification_view()
    application.decision_view()
    application.audit_timeline()
    third = application.current_investigation()
    assert second.id == first.id
    assert third is not None
    assert len(second.audit_events) == len(third.audit_events) == first_audit_count
    assert len(second.claims) == len(first.claims)


def test_offline_provider_selection_requires_no_credentials(tmp_path: Path) -> None:
    application = DemoApplication(
        provider_name="offline", environment={}, default_adc_path=tmp_path / "missing-adc.json"
    )
    investigation = application.trigger()
    assert investigation.reasoning_provider == "offline"
    assert investigation.configured_model_id is None


def test_unavailable_gemini_fails_gracefully_without_fallback(tmp_path: Path) -> None:
    adc_path = tmp_path / "missing-adc.json"
    status = gemini_availability({}, default_adc_path=adc_path)
    assert status.available is False
    application = DemoApplication(
        provider_name="gemini", environment={}, default_adc_path=adc_path
    )
    with pytest.raises(GeminiUnavailableError, match="Configure GEMINI_API_KEY"):
        application.trigger()
    assert not application.triggered
    assert application.current_investigation() is None


def test_verification_view_preserves_rejected_and_revised_claims() -> None:
    application = DemoApplication()
    application.trigger()
    view = application.verification_view()
    assert view is not None
    assert view.rejected_claim is not None
    assert view.rejected_claim.claim_id == "claim-001"
    assert view.rejected_claim.value == 4.1
    assert view.rejected_claim.status == ClaimStatus.REJECTED.value
    assert view.revised_claim is not None
    assert view.revised_claim.value == 3.8
    assert view.revised_claim.status == ClaimStatus.VERIFIED.value
    assert view.revised_claim.supersedes_claim_id == "claim-001"
    assert [support.value for support in view.support_values] == [4.1, 3.8, 3.8]


def test_permission_denial_is_exposed_with_actor_capability_and_reason() -> None:
    application = DemoApplication()
    application.trigger()
    view = application.verification_view()
    assert view is not None
    assert view.permission_denial is not None
    assert view.permission_denial.actor == "credit_agent"
    assert view.permission_denial.capability == "read_portfolio_positions"
    assert "not granted" in view.permission_denial.rationale


def test_decision_view_keeps_all_status_dimensions_separate() -> None:
    application = DemoApplication()
    application.trigger()
    view = application.decision_view()
    assert view is not None
    assert view.machine_verification == "PASSED"
    assert view.risk_classification == "RED"
    assert view.governance_status == GovernanceStatus.HUMAN_REVIEW_REQUIRED.value
    assert view.human_review_status == HumanReviewStatus.REQUIRED.value
    assert view.lifecycle_status == LifecycleStatus.AWAITING_HUMAN_REVIEW.value


@pytest.mark.parametrize(
    ("reviewer", "rationale", "message"),
    (("", "Reason", "Reviewer"), ("Reviewer", " ", "rationale")),
)
def test_human_decision_requires_reviewer_and_rationale(
    reviewer: str, rationale: str, message: str
) -> None:
    application = DemoApplication()
    application.trigger()
    with pytest.raises(DecisionInputError, match=message):
        application.record_human_decision(
            action=HumanAction.APPROVE,
            reviewer=reviewer,
            rationale=rationale,
        )
    investigation = application.current_investigation()
    assert investigation is not None
    assert not investigation.human_decisions


def test_valid_human_decision_routes_through_domain_workflow() -> None:
    application = DemoApplication()
    application.trigger()
    completed = application.record_human_decision(
        action=HumanAction.APPROVE,
        reviewer="Judge Demo Reviewer",
        rationale="Reviewed the verified correction and audit lineage.",
    )
    assert completed.lifecycle_status == LifecycleStatus.COMPLETED
    assert completed.human_review_status == HumanReviewStatus.APPROVED
    stored = application.current_investigation()
    assert stored is not None
    assert stored.human_decisions[-1].reviewer == "Judge Demo Reviewer"


def test_request_more_investigation_returns_case_to_investigating() -> None:
    application = DemoApplication()
    application.trigger()
    returned = application.record_human_decision(
        action=HumanAction.REQUEST_MORE_INVESTIGATION,
        reviewer="Judge Demo Reviewer",
        rationale="Request issuer-specific liquidity evidence.",
    )
    assert returned.lifecycle_status == LifecycleStatus.INVESTIGATING
    assert returned.governance_status == GovernanceStatus.PENDING
    assert returned.human_review_status == HumanReviewStatus.MORE_INVESTIGATION


def test_three_reset_and_run_cycles_are_deterministic() -> None:
    application = DemoApplication()
    audit_counts: list[int] = []
    for _ in range(3):
        investigation = application.trigger()
        audit_counts.append(len(investigation.audit_events))
        assert investigation.claims["claim-001"].value == 4.1
        assert investigation.claims["claim-002"].value == 3.8
        application.reset()
    assert len(set(audit_counts)) == 1
