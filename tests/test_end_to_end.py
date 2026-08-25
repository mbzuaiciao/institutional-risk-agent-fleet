import sys

from institutional_risk_fleet.demo import main
from institutional_risk_fleet.domain import (
    ClaimStatus,
    EventType,
    GovernanceStatus,
    HumanAction,
    LifecycleStatus,
    TaskStatus,
)
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


def test_complete_offline_acceptance_scenario() -> None:
    workflow = DeterministicRiskWorkflow()
    investigation = workflow.run()
    assert all(task.status == TaskStatus.COMPLETE for task in investigation.tasks.values())
    assert investigation.claims["claim-001"].status == ClaimStatus.REJECTED
    assert investigation.claims["claim-002"].status == ClaimStatus.VERIFIED
    assert investigation.governance_status == GovernanceStatus.HUMAN_REVIEW_REQUIRED
    assert any(
        event.event_type == EventType.PERMISSION_DENIED for event in investigation.audit_events
    )
    completed = workflow.record_human_decision(
        investigation.id,
        action=HumanAction.APPROVE,
        reviewer="Acceptance Test Reviewer",
        rationale="All deterministic governance invariants passed.",
    )
    assert completed.lifecycle_status == LifecycleStatus.COMPLETED


def test_demo_entry_point_is_readable_and_offline(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "argv", ["risk-fleet-demo"])
    main()
    output = capsys.readouterr().out
    assert "Credit Agent portfolio request: DENIED" in output
    assert "observed 4.1x, expected 3.8x" in output
    assert "Machine verification: PASSED" in output
    assert "HUMAN_REVIEW_REQUIRED" in output
