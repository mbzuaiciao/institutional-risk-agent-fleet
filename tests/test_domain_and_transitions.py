import pytest
from pydantic import ValidationError

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    Claim,
    ClaimType,
    Investigation,
    LifecycleStatus,
    Role,
)
from institutional_risk_fleet.scenario import load_default_scenario
from institutional_risk_fleet.transitions import transition_lifecycle


def test_material_factual_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence lineage"):
        Claim(
            id="claim-invalid",
            author=Role.CREDIT,
            claim_type=ClaimType.FACTUAL,
            text="A material factual claim.",
            confidence=0.5,
        )

def test_calculated_claim_requires_tool_lineage() -> None:
    with pytest.raises(ValidationError, match="tool lineage"):
        Claim(
            id="claim-invalid",
            author=Role.CREDIT,
            claim_type=ClaimType.CALCULATED,
            text="Leverage is 3.8x.",
            metric="fy2025_leverage",
            value=3.8,
            unit="x",
            period="FY2025",
            confidence=1.0,
        )


def test_valid_lifecycle_transition_is_recorded() -> None:
    investigation = Investigation(id="inv-test", event=load_default_scenario().event)
    audit = AuditLog()
    transition_lifecycle(
        investigation,
        LifecycleStatus.INVESTIGATING,
        actor=Role.ORCHESTRATOR,
        audit=audit,
    )
    assert investigation.lifecycle_status == LifecycleStatus.INVESTIGATING
    assert investigation.audit_events[-1].details["previous"] == "CREATED"


def test_invalid_lifecycle_transition_is_rejected() -> None:
    investigation = Investigation(id="inv-test", event=load_default_scenario().event)
    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        transition_lifecycle(
            investigation,
            LifecycleStatus.VERIFYING,
            actor=Role.ORCHESTRATOR,
            audit=AuditLog(),
        )
