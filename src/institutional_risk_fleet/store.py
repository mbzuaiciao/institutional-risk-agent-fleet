"""Replaceable state-store boundary with an in-memory Milestones 0-2 implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol

from institutional_risk_fleet.domain import Investigation


class StateStore(Protocol):
    def create(self, investigation: Investigation) -> None: ...

    def get(self, investigation_id: str) -> Investigation: ...

    def save(self, investigation: Investigation) -> None: ...

    def update_atomically(
        self,
        investigation_id: str,
        update: Callable[[Investigation], Investigation],
    ) -> Investigation: ...

    def delete_demo_investigation(self, investigation_id: str) -> None: ...

    def reserve_event(
        self, event_id: str, investigation_id: str, delivery_id: str
    ) -> EventReservation: ...

    def complete_event(self, event_id: str, investigation_id: str) -> None: ...

    def release_event(self, event_id: str, delivery_id: str) -> None: ...

    def reset_demo_event(self, event_id: str, investigation_id: str) -> None: ...


@dataclass(frozen=True)
class EventReservation:
    acquired: bool
    investigation_id: str
    status: str


class InMemoryStateStore:
    def __init__(self) -> None:
        self._investigations: dict[str, Investigation] = {}
        self._event_receipts: dict[str, dict[str, object]] = {}
        self._lock = RLock()

    def create(self, investigation: Investigation) -> None:
        with self._lock:
            if investigation.id in self._investigations:
                raise ValueError(f"investigation already exists: {investigation.id}")
            self._investigations[investigation.id] = investigation.model_copy(deep=True)

    def get(self, investigation_id: str) -> Investigation:
        with self._lock:
            try:
                return self._investigations[investigation_id].model_copy(deep=True)
            except KeyError as error:
                raise KeyError(f"unknown investigation: {investigation_id}") from error

    def save(self, investigation: Investigation) -> None:
        with self._lock:
            if investigation.id not in self._investigations:
                raise KeyError(f"unknown investigation: {investigation.id}")
            self._investigations[investigation.id] = investigation.model_copy(deep=True)

    def update_atomically(
        self,
        investigation_id: str,
        update: Callable[[Investigation], Investigation],
    ) -> Investigation:
        with self._lock:
            current = self.get(investigation_id)
            updated = update(current)
            if updated.id != investigation_id:
                raise ValueError("atomic update cannot change investigation ID")
            self._investigations[investigation_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)

    def delete_demo_investigation(self, investigation_id: str) -> None:
        with self._lock:
            self._investigations.pop(investigation_id, None)

    def reserve_event(
        self, event_id: str, investigation_id: str, delivery_id: str
    ) -> EventReservation:
        with self._lock:
            now = datetime.now(UTC)
            receipt = self._event_receipts.get(event_id)
            if receipt is not None:
                lease_expires_at = receipt.get("lease_expires_at")
                if receipt["status"] == "completed" or (
                    isinstance(lease_expires_at, datetime) and lease_expires_at > now
                ):
                    return EventReservation(
                        False, str(receipt["investigation_id"]), str(receipt["status"])
                    )
            self._event_receipts[event_id] = {
                "status": "processing",
                "investigation_id": investigation_id,
                "delivery_id": delivery_id,
                "lease_expires_at": now + timedelta(minutes=10),
            }
            return EventReservation(True, investigation_id, "processing")

    def complete_event(self, event_id: str, investigation_id: str) -> None:
        with self._lock:
            receipt = self._event_receipts[event_id]
            receipt.update(status="completed", investigation_id=investigation_id)

    def release_event(self, event_id: str, delivery_id: str) -> None:
        with self._lock:
            receipt = self._event_receipts.get(event_id)
            if receipt and receipt.get("delivery_id") == delivery_id:
                self._event_receipts.pop(event_id, None)

    def reset_demo_event(self, event_id: str, investigation_id: str) -> None:
        with self._lock:
            receipt = self._event_receipts.get(event_id)
            if receipt and receipt.get("status") == "processing":
                expires = receipt.get("lease_expires_at")
                if isinstance(expires, datetime) and expires > datetime.now(UTC):
                    raise ValueError("cannot reset the demo while event processing is active")
            self._event_receipts.pop(event_id, None)
            self._investigations.pop(investigation_id, None)
