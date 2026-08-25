import pytest

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import EventType, Investigation, Role
from institutional_risk_fleet.permissions import CapabilityGate, PermissionDenied, RoleContext
from institutional_risk_fleet.scenario import load_default_scenario
from institutional_risk_fleet.tools import ToolGateway


def _investigation() -> Investigation:
    return Investigation(id="inv-test", event=load_default_scenario().event)


def test_credit_leverage_tool_is_deterministic_and_unit_explicit() -> None:
    investigation = _investigation()
    audit = AuditLog()
    result = ToolGateway(
        RoleContext(Role.CREDIT), CapabilityGate(audit), audit
    ).execute(
        investigation,
        "leverage_ratio",
        {"debt_usd_millions": 380.0, "ebitda_usd_millions": 100.0},
    )
    assert result.successful
    assert result.output == 3.8
    assert result.units == "x"
    assert result.actor == Role.CREDIT
    assert result.tool_version == "1.0"


def test_spread_move_and_duration_pnl_units() -> None:
    investigation = _investigation()
    audit = AuditLog()
    market = ToolGateway(RoleContext(Role.MARKET), CapabilityGate(audit), audit)
    spread = market.execute(
        investigation,
        "spread_move",
        {"previous_spread_bps": 120.0, "current_spread_bps": 210.0},
    )
    investigator = ToolGateway(RoleContext(Role.INVESTIGATOR), CapabilityGate(audit), audit)
    pnl = investigator.execute(
        investigation,
        "duration_spread_pnl",
        {"market_value_usd": 75_000_000.0, "spread_duration": 4.2, "spread_move_bps": 90.0},
    )
    assert (spread.output, spread.units) == (90.0, "bps")
    assert (pnl.output, pnl.units) == (-2_835_000.0, "USD")


def test_unauthorized_credit_portfolio_request_is_denied_and_audited() -> None:
    investigation = _investigation()
    audit = AuditLog()
    gateway = ToolGateway(RoleContext(Role.CREDIT), CapabilityGate(audit), audit)
    with pytest.raises(PermissionDenied):
        gateway.execute(
            investigation,
            "portfolio_exposure",
            {"position_market_values_usd": [75_000_000.0]},
        )
    denied = [
        event for event in investigation.audit_events if event.event_type == EventType.PERMISSION_DENIED
    ]
    assert len(denied) == 1
    assert denied[0].actor == Role.CREDIT
    assert denied[0].details["capability"] == "read_portfolio_positions"
    assert investigation.tool_executions == {}
