"""Validated deterministic financial tools behind a role-bound gateway."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import EventType, Investigation, ToolExecution
from institutional_risk_fleet.permissions import (
    Capability,
    CapabilityGate,
    RoleContext,
)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpreadMoveInput(ToolInput):
    previous_spread_bps: float = Field(ge=0)
    current_spread_bps: float = Field(ge=0)


class LeverageInput(ToolInput):
    debt_usd_millions: float = Field(gt=0)
    ebitda_usd_millions: float = Field(gt=0)


class SpreadPnlInput(ToolInput):
    market_value_usd: float = Field(gt=0)
    spread_duration: float = Field(gt=0)
    spread_move_bps: float


class PortfolioExposureInput(ToolInput):
    position_market_values_usd: tuple[float, ...] = Field(min_length=1)


ToolFunction = Callable[[Any], float]


def _spread_move(data: SpreadMoveInput) -> float:
    return round(data.current_spread_bps - data.previous_spread_bps, 4)


def _leverage(data: LeverageInput) -> float:
    return round(data.debt_usd_millions / data.ebitda_usd_millions, 4)


def _spread_pnl(data: SpreadPnlInput) -> float:
    return round(-data.market_value_usd * data.spread_duration * data.spread_move_bps / 10_000, 2)


def _portfolio_exposure(data: PortfolioExposureInput) -> float:
    return round(sum(data.position_market_values_usd), 2)


class ToolDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    name: str
    version: str
    input_model: type[ToolInput]
    function: ToolFunction
    units: str
    capability: Capability
    provenance: str


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "spread_move": ToolDefinition(
        name="spread_move",
        version="1.0",
        input_model=SpreadMoveInput,
        function=_spread_move,
        units="bps",
        capability=Capability.CALL_MARKET_TOOL,
        provenance="current_spread_bps - previous_spread_bps",
    ),
    "leverage_ratio": ToolDefinition(
        name="leverage_ratio",
        version="1.0",
        input_model=LeverageInput,
        function=_leverage,
        units="x",
        capability=Capability.CALL_CREDIT_TOOL,
        provenance="debt_usd_millions / ebitda_usd_millions",
    ),
    "duration_spread_pnl": ToolDefinition(
        name="duration_spread_pnl",
        version="1.0",
        input_model=SpreadPnlInput,
        function=_spread_pnl,
        units="USD",
        capability=Capability.CALL_PORTFOLIO_TOOL,
        provenance="-market_value_usd * spread_duration * spread_move_bps / 10000",
    ),
    "portfolio_exposure": ToolDefinition(
        name="portfolio_exposure",
        version="1.0",
        input_model=PortfolioExposureInput,
        function=_portfolio_exposure,
        units="USD",
        capability=Capability.READ_PORTFOLIO_POSITIONS,
        provenance="sum(position_market_values_usd)",
    ),
}


class ToolGateway:
    """Gateway identity is fixed at construction and cannot be overridden per call."""

    def __init__(
        self,
        context: RoleContext,
        gate: CapabilityGate,
        audit: AuditLog,
    ) -> None:
        self.context = context
        self.gate = gate
        self.audit = audit

    def execute(
        self, investigation: Investigation, tool_name: str, arguments: dict[str, Any]
    ) -> ToolExecution:
        try:
            definition = TOOL_DEFINITIONS[tool_name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {tool_name}") from error
        request_index = (
            sum(event.event_type == EventType.TOOL_REQUESTED for event in investigation.audit_events)
            + 1
        )
        request_id = f"tool-request-{request_index:03d}"
        self.audit.append(
            investigation,
            EventType.TOOL_REQUESTED,
            self.context.role,
            request_id,
            tool=tool_name,
        )
        self.gate.require(
            self.context,
            definition.capability,
            investigation,
            related_object_id=request_id,
        )
        execution_id = f"tool-execution-{len(investigation.tool_executions) + 1:03d}"
        try:
            validated = definition.input_model.model_validate(arguments)
            output = definition.function(validated)
            execution = ToolExecution(
                id=execution_id,
                tool_name=definition.name,
                tool_version=definition.version,
                actor=self.context.role,
                inputs=validated.model_dump(mode="json"),
                output=output,
                units=definition.units,
                successful=True,
                provenance=definition.provenance,
            )
            investigation.tool_executions[execution.id] = execution
            self.audit.append(
                investigation,
                EventType.TOOL_EXECUTED,
                self.context.role,
                execution.id,
                tool=tool_name,
                units=definition.units,
                output=output,
            )
            return execution
        except Exception as error:
            execution = ToolExecution(
                id=execution_id,
                tool_name=definition.name,
                tool_version=definition.version,
                actor=self.context.role,
                inputs=arguments,
                output=None,
                units=definition.units,
                successful=False,
                provenance=definition.provenance,
                error=str(error),
            )
            investigation.tool_executions[execution.id] = execution
            self.audit.append(
                investigation,
                EventType.TOOL_FAILED,
                self.context.role,
                execution.id,
                tool=tool_name,
                error=str(error),
            )
            return execution
