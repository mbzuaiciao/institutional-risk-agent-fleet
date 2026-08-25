import pytest

from institutional_risk_fleet.audit import assert_coherent_audit
from institutional_risk_fleet.domain import (
    EventType,
    HumanAction,
    HumanReviewStatus,
    LifecycleStatus,
)
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


def test_human_required_investigation_cannot_complete_without_decision() -> None:
    workflow = DeterministicRiskWorkflow()
    investigation = workflow.run()
    with pytest.raises(ValueError, match="cannot complete"):
        workflow.complete_investigation(investigation)


def test_approve_records_identity_rationale_and_completes() -> None:
    workflow = DeterministicRiskWorkflow()
    investigation = workflow.run()
    completed = workflow.record_human_decision(
        investigation.id,
        action=HumanAction.APPROVE,
        reviewer="A. Risk Officer",
        rationale="Reviewed the corrected claim and synthetic evidence.",
    )
    assert completed.lifecycle_status == LifecycleStatus.COMPLETED
    assert completed.human_review_status == HumanReviewStatus.APPROVED
    assert completed.human_decisions[-1].reviewer == "A. Risk Officer"
    assert completed.human_decisions[-1].rationale
    assert completed.audit_events[-1].event_type == EventType.INVESTIGATION_COMPLETED


def test_request_more_investigation_is_not_final_completion() -> None:
    workflow = DeterministicRiskWorkflow()
    investigation = workflow.run()
    returned = workflow.record_human_decision(
        investigation.id,
        action=HumanAction.REQUEST_MORE_INVESTIGATION,
        reviewer="A. Risk Officer",
        rationale="Investigate sector contagion further.",
    )
    assert returned.lifecycle_status == LifecycleStatus.INVESTIGATING
    assert returned.human_review_status == HumanReviewStatus.MORE_INVESTIGATION
    assert not any(
        event.event_type == EventType.INVESTIGATION_COMPLETED
        for event in returned.audit_events
    )


def test_audit_sequence_and_required_event_types_are_coherent() -> None:
    investigation = DeterministicRiskWorkflow().run()
    assert_coherent_audit(investigation)
    assert [event.sequence for event in investigation.audit_events] == list(
        range(1, len(investigation.audit_events) + 1)
    )
    required = {
        EventType.RISK_EVENT_RECEIVED,
        EventType.INVESTIGATION_STARTED,
        EventType.TASK_CREATED,
        EventType.TOOL_REQUESTED,
        EventType.PERMISSION_DENIED,
        EventType.TOOL_EXECUTED,
        EventType.EVIDENCE_ADDED,
        EventType.CLAIM_CREATED,
        EventType.VERIFICATION_FAILED,
        EventType.CLAIM_REVISED,
        EventType.VERIFICATION_PASSED,
        EventType.GOVERNANCE_EVALUATED,
        EventType.HUMAN_REVIEW_REQUIRED,
    }
    assert required <= {event.event_type for event in investigation.audit_events}
