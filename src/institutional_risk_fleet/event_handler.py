"""One validated risk-event application handler shared by local and cloud entry points."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from institutional_risk_fleet.domain import Investigation
from institutional_risk_fleet.reasoning import ReasoningProvider
from institutional_risk_fleet.scenario import load_default_scenario
from institutional_risk_fleet.store import StateStore
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow

EVENT_ID = "risk-event-acme-001"
SCENARIO_ID = "acme-synthetic-v1"
INVESTIGATION_ID = "investigation-acme-001"


class RiskEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    event_id: str
    scenario_id: str


@dataclass(frozen=True)
class EventHandlingResult:
    investigation: Investigation | None
    duplicate: bool
    status: str


class RiskEventApplication:
    def __init__(self, store: StateStore, provider: ReasoningProvider) -> None:
        self.store = store
        self.provider = provider

    def handle(self, envelope: RiskEventEnvelope, *, delivery_id: str) -> EventHandlingResult:
        self._validate_known_event(envelope)
        try:
            reservation = self.store.reserve_event(EVENT_ID, INVESTIGATION_ID, delivery_id)
        except Exception:
            _log(
                "event_store_unavailable",
                level=logging.ERROR,
                event_id=envelope.event_id,
                investigation_id=INVESTIGATION_ID,
                delivery_id=delivery_id,
            )
            raise
        if not reservation.acquired:
            try:
                investigation = self.store.get(reservation.investigation_id)
            except KeyError:
                investigation = None
            _log(
                "duplicate_event",
                event_id=envelope.event_id,
                investigation_id=reservation.investigation_id,
                delivery_id=delivery_id,
                status=reservation.status,
            )
            return EventHandlingResult(investigation, True, reservation.status)
        try:
            try:
                existing = self.store.get(INVESTIGATION_ID)
            except KeyError:
                existing = None
            if existing is not None:
                self.store.complete_event(EVENT_ID, INVESTIGATION_ID)
                return EventHandlingResult(existing, True, "completed")
            investigation = DeterministicRiskWorkflow(
                store=self.store, reasoning_provider=self.provider
            ).run(load_default_scenario())
            self.store.complete_event(EVENT_ID, investigation.id)
            _log(
                "event_completed",
                event_id=envelope.event_id,
                investigation_id=investigation.id,
                lifecycle_state=investigation.lifecycle_status.value,
                audit_event=investigation.audit_events[-1].event_type.value,
            )
            return EventHandlingResult(investigation, False, "completed")
        except Exception:
            self.store.delete_demo_investigation(INVESTIGATION_ID)
            self.store.release_event(EVENT_ID, delivery_id)
            _log(
                "event_failed",
                level=logging.ERROR,
                event_id=envelope.event_id,
                investigation_id=INVESTIGATION_ID,
                delivery_id=delivery_id,
            )
            raise

    @staticmethod
    def _validate_known_event(envelope: RiskEventEnvelope) -> None:
        if envelope.event_id != EVENT_ID or envelope.scenario_id != SCENARIO_ID:
            _log(
                "event_rejected",
                level=logging.WARNING,
                event_id=envelope.event_id,
                scenario_id=envelope.scenario_id,
            )
            raise ValueError("unknown event_id or scenario_id")


def _log(message: str, *, level: int = logging.INFO, **fields: object) -> None:
    print(
        json.dumps(
            {"severity": logging.getLevelName(level), "message": message, **fields},
            separators=(",", ":"),
        ),
        flush=True,
    )
