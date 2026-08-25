import pytest
from pydantic import ValidationError

from institutional_risk_fleet.domain import (
    ClaimStatus,
    FindingResult,
    GovernanceStatus,
    HumanReviewStatus,
    LifecycleStatus,
    RiskClassification,
)
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


def test_seeded_4_1_claim_fails_and_corrected_claim_passes() -> None:
    investigation = DeterministicRiskWorkflow().run()
    failed = next(
        finding
        for finding in investigation.verification_findings
        if finding.target_claim_id == "claim-001"
    )
    passed = next(
        finding
        for finding in investigation.verification_findings
        if finding.target_claim_id == "claim-002"
    )
    assert failed.result == FindingResult.FAILED
    assert failed.observed_value == 4.1
    assert failed.expected_value == 3.8
    assert failed.units == "x"
    assert passed.result == FindingResult.PASSED
    assert passed.observed_value == passed.expected_value == 3.8


def test_rejected_claim_is_preserved_and_revision_supersedes_it() -> None:
    investigation = DeterministicRiskWorkflow().run()
    rejected = investigation.claims["claim-001"]
    corrected = investigation.claims["claim-002"]
    assert rejected.value == 4.1
    assert rejected.status == ClaimStatus.REJECTED
    assert corrected.value == 3.8
    assert corrected.status == ClaimStatus.VERIFIED
    assert corrected.supersedes_claim_id == rejected.id
    with pytest.raises(ValidationError):
        rejected.value = 3.8  # type: ignore[misc]


def test_unresolved_critical_failure_cannot_machine_pass() -> None:
    investigation = DeterministicRiskWorkflow().run()
    first = investigation.governance_decisions[0]
    assert not first.machine_verification_passed
    assert first.status == GovernanceStatus.REVISION_REQUIRED
    assert "unresolved_critical_verification_failure" in first.triggered_rules


def test_high_material_event_machine_passes_but_requires_human() -> None:
    investigation = DeterministicRiskWorkflow().run()
    final = investigation.governance_decisions[-1]
    assert final.machine_verification_passed
    assert final.status == GovernanceStatus.HUMAN_REVIEW_REQUIRED
    assert final.risk_classification == RiskClassification.RED
    assert investigation.lifecycle_status == LifecycleStatus.AWAITING_HUMAN_REVIEW
    assert investigation.human_review_status == HumanReviewStatus.REQUIRED
