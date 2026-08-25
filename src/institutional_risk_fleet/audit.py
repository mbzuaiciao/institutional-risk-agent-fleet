"""Logical append-only audit event construction."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from institutional_risk_fleet.domain import AuditEvent, EventType, Investigation, Role


class AuditLog:
    """The only application API for adding audit events."""

    def append(
        self,
        investigation: Investigation,
        event_type: EventType,
        actor: Role,
        related_object_id: str | None = None,
        **details: Any,
    ) -> AuditEvent:
        sequence = len(investigation.audit_events) + 1
        event = AuditEvent(
            sequence=sequence,
            id=f"audit-{investigation.id}-{sequence:04d}",
            investigation_id=investigation.id,
            actor=actor,
            event_type=event_type,
            related_object_id=related_object_id,
            details=details,
            timestamp=investigation.event.occurred_at + timedelta(milliseconds=sequence),
        )
        investigation.audit_events.append(event)
        return event


def assert_coherent_audit(investigation: Investigation) -> None:
    expected_sequences = list(range(1, len(investigation.audit_events) + 1))
    actual_sequences = [event.sequence for event in investigation.audit_events]
    if actual_sequences != expected_sequences:
        raise ValueError("audit sequence is not contiguous")
    ids = [event.id for event in investigation.audit_events]
    if len(ids) != len(set(ids)):
        raise ValueError("audit event IDs must be unique")
    if any(event.investigation_id != investigation.id for event in investigation.audit_events):
        raise ValueError("audit event belongs to a different investigation")
