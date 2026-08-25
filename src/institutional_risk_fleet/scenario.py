"""Loader and validation for the single frozen synthetic Acme scenario."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from institutional_risk_fleet.domain import Evidence, RiskEvent


class IssuerFinancials(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    period: str
    debt_usd_millions: float = Field(gt=0)
    cash_usd_millions: float = Field(ge=0)
    ebitda_usd_millions: float = Field(gt=0)


class PortfolioPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    issuer_name: str
    market_value_usd: float = Field(gt=0)
    spread_duration: float = Field(gt=0)


class ComparableIssuer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    spread_bps: float = Field(ge=0)
    leverage: float = Field(gt=0)


class FrozenScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scenario_id: str
    version: str
    synthetic: bool
    disclaimer: str
    event: RiskEvent
    financials: IssuerFinancials
    positions: tuple[PortfolioPosition, ...]
    comparable_issuers: tuple[ComparableIssuer, ...]
    historical_spreads_bps: tuple[float, ...]
    evidence: tuple[Evidence, ...]

    @model_validator(mode="after")
    def validate_frozen_case(self) -> FrozenScenario:
        if not self.synthetic or "synthetic" not in self.disclaimer.lower():
            raise ValueError("scenario must be clearly labeled synthetic")
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        position_ids = [item.id for item in self.positions]
        if len(position_ids) != len(set(position_ids)):
            raise ValueError("position IDs must be unique")
        return self


def default_scenario_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "synthetic" / "acme_scenario.json"


def load_default_scenario(path: Path | None = None) -> FrozenScenario:
    selected = path or default_scenario_path()
    return FrozenScenario.model_validate(json.loads(selected.read_text(encoding="utf-8")))
