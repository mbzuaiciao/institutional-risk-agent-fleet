"""Authoritative investigation lifecycle transitions."""

from __future__ import annotations

from institutional_risk_fleet.audit import AuditLog
from institutional_risk_fleet.domain import (
    EventType,
    Investigation,
    LifecycleStatus,
    Role,
)

ALLOWED_TRANSITIONS: dict[LifecycleStatus, frozenset[LifecycleStatus]] = {
    LifecycleStatus.CREATED: frozenset({LifecycleStatus.INVESTIGATING}),
    LifecycleStatus.INVESTIGATING: frozenset(
        {LifecycleStatus.VERIFYING, LifecycleStatus.AWAITING_HUMAN_REVIEW}
    ),
    LifecycleStatus.VERIFYING: frozenset(
        {LifecycleStatus.REVISING, LifecycleStatus.AWAITING_HUMAN_REVIEW, LifecycleStatus.COMPLETED}
    ),
    LifecycleStatus.REVISING: frozenset({LifecycleStatus.VERIFYING}),
    LifecycleStatus.AWAITING_HUMAN_REVIEW: frozenset(
        {LifecycleStatus.COMPLETED, LifecycleStatus.INVESTIGATING}
    ),
    LifecycleStatus.COMPLETED: frozenset(),
}


def transition_lifecycle(
    investigation: Investigation,
    target: LifecycleStatus,
    *,
    actor: Role,
    audit: AuditLog,
) -> None:
    previous = investigation.lifecycle_status
    if target not in ALLOWED_TRANSITIONS[previous]:
        raise ValueError(f"invalid lifecycle transition: {previous} -> {target}")
    investigation.lifecycle_status = target
    audit.append(
        investigation,
        EventType.LIFECYCLE_TRANSITIONED,
        actor,
        investigation.id,
        previous=previous.value,
        current=target.value,
    )
