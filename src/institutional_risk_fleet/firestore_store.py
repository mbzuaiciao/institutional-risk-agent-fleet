"""Firestore persistence adapter; domain invariants remain in application code."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import firestore

from institutional_risk_fleet.domain import Investigation
from institutional_risk_fleet.store import EventReservation

_COLLECTIONS = (
    "tasks",
    "evidence",
    "claims",
    "tool_executions",
    "theses",
    "challenges",
    "model_calls",
    "verification_findings",
    "governance_decisions",
    "human_decisions",
    "audit_events",
)


def _create_firestore_client(*, project: str, database: str) -> Any:
    """Construct a client and isolate the pinned default-database path workaround.

    google-cloud-firestore 2.29.0 accepts ``database="(default)"`` through its public API but
    currently renders that resource segment as ``%28default%29``. The live Firestore API rejects
    that resource name. Limit the private-field compatibility shim to clients constructed here and
    to the default database only; injected clients and named databases remain untouched.
    """
    client = firestore.Client(project=project, database=database)
    if database == "(default)" and "%28default%29" in client._database_string:
        client._database_string_internal = f"projects/{project}/databases/(default)"
    return client


def serialize_investigation(investigation: Investigation) -> dict[str, Any]:
    """Return the canonical, JSON-safe representation stored in the root document."""
    return investigation.model_dump(mode="json")


def deserialize_investigation(payload: dict[str, Any]) -> Investigation:
    return Investigation.model_validate(payload)


def investigation_documents(
    investigation: Investigation,
) -> dict[str, tuple[tuple[str, dict[str, Any]], ...]]:
    """Create independently queryable snapshots while retaining one canonical root payload."""
    data = serialize_investigation(investigation)

    def mapping(name: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple((key, value) for key, value in data[name].items())

    def sequence(name: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple((item["id"], item) for item in data[name])

    return {
        "tasks": mapping("tasks"),
        "evidence": mapping("evidence"),
        "claims": mapping("claims"),
        "tool_executions": mapping("tool_executions"),
        "theses": mapping("theses"),
        "challenges": sequence("challenges"),
        "model_calls": sequence("model_calls"),
        "verification_findings": sequence("verification_findings"),
        "governance_decisions": sequence("governance_decisions"),
        "human_decisions": sequence("human_decisions"),
        "audit_events": sequence("audit_events"),
    }


class FirestoreStateStore:
    """Canonical root snapshots plus queryable artifact subcollections.

    Complete investigations are reconstructed from the root payload. Writes preserve stable
    artifact IDs, and transactions serialize human decisions and event reservations.
    """

    def __init__(
        self,
        *,
        project: str,
        database: str = "(default)",
        client: Any | None = None,
    ) -> None:
        self._client = client or _create_firestore_client(project=project, database=database)
        self._investigations = self._client.collection("investigations")
        self._events = self._client.collection("event_receipts")

    def create(self, investigation: Investigation) -> None:
        reference = self._investigations.document(investigation.id)
        transaction = self._client.transaction()

        @firestore.transactional
        def create_once(transaction: Any) -> None:
            if reference.get(transaction=transaction).exists:
                raise ValueError(f"investigation already exists: {investigation.id}")
            self._write_snapshot(transaction, reference, investigation)

        create_once(transaction)

    def get(self, investigation_id: str) -> Investigation:
        snapshot = self._investigations.document(investigation_id).get()
        if not snapshot.exists:
            raise KeyError(f"unknown investigation: {investigation_id}")
        data = snapshot.to_dict() or {}
        return deserialize_investigation(data["payload"])

    def save(self, investigation: Investigation) -> None:
        reference = self._investigations.document(investigation.id)
        if not reference.get().exists:
            raise KeyError(f"unknown investigation: {investigation.id}")
        batch = self._client.batch()
        self._write_snapshot(batch, reference, investigation)
        batch.commit()

    def update_atomically(
        self,
        investigation_id: str,
        update: Callable[[Investigation], Investigation],
    ) -> Investigation:
        reference = self._investigations.document(investigation_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def apply(transaction: Any) -> Investigation:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                raise KeyError(f"unknown investigation: {investigation_id}")
            current = deserialize_investigation((snapshot.to_dict() or {})["payload"])
            updated = update(current)
            if updated.id != investigation_id:
                raise ValueError("atomic update cannot change investigation ID")
            self._write_snapshot(transaction, reference, updated)
            return updated

        return apply(transaction).model_copy(deep=True)

    def delete_demo_investigation(self, investigation_id: str) -> None:
        self._delete_investigation(investigation_id)

    def reserve_event(
        self, event_id: str, investigation_id: str, delivery_id: str
    ) -> EventReservation:
        reference = self._events.document(event_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve(transaction: Any) -> EventReservation:
            snapshot = reference.get(transaction=transaction)
            now = datetime.now(UTC)
            if snapshot.exists:
                data = snapshot.to_dict() or {}
                expires = data.get("lease_expires_at")
                if data.get("status") == "completed" or (
                    isinstance(expires, datetime) and expires > now
                ):
                    return EventReservation(
                        False,
                        str(data.get("investigation_id", investigation_id)),
                        str(data.get("status", "processing")),
                    )
            transaction.set(
                reference,
                {
                    "event_id": event_id,
                    "investigation_id": investigation_id,
                    "delivery_id": delivery_id,
                    "status": "processing",
                    "lease_expires_at": now + timedelta(minutes=10),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
            )
            return EventReservation(True, investigation_id, "processing")

        return reserve(transaction)

    def complete_event(self, event_id: str, investigation_id: str) -> None:
        self._events.document(event_id).update(
            {
                "status": "completed",
                "investigation_id": investigation_id,
                "lease_expires_at": firestore.DELETE_FIELD,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
        )

    def release_event(self, event_id: str, delivery_id: str) -> None:
        reference = self._events.document(event_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def release(transaction: Any) -> None:
            snapshot = reference.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data and data.get("delivery_id") == delivery_id and data.get("status") == "processing":
                transaction.delete(reference)

        release(transaction)

    def reset_demo_event(self, event_id: str, investigation_id: str) -> None:
        if event_id != "risk-event-acme-001" or investigation_id != "investigation-acme-001":
            raise ValueError("reset is restricted to the frozen ACME demonstration")
        event_reference = self._events.document(event_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve_reset(transaction: Any) -> None:
            snapshot = event_reference.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data and data.get("status") == "processing":
                expires = data.get("lease_expires_at")
                if isinstance(expires, datetime) and expires > datetime.now(UTC):
                    raise ValueError("cannot reset the demo while event processing is active")
            transaction.delete(event_reference)

        reserve_reset(transaction)
        self._delete_investigation(investigation_id)

    def _write_snapshot(self, writer: Any, reference: Any, investigation: Investigation) -> None:
        payload = serialize_investigation(investigation)
        writer.set(
            reference,
            {
                "payload": payload,
                "event_id": investigation.event.id,
                "lifecycle_status": investigation.lifecycle_status.value,
                "governance_status": investigation.governance_status.value,
                "risk_classification": investigation.risk_classification.value,
                "human_review_status": investigation.human_review_status.value,
                "reasoning_provider": investigation.reasoning_provider,
                "configured_model_id": investigation.configured_model_id,
                "audit_sequence": len(investigation.audit_events),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
        )
        for collection, documents in investigation_documents(investigation).items():
            for document_id, document in documents:
                writer.set(reference.collection(collection).document(document_id), document)

    def _delete_investigation(self, investigation_id: str) -> None:
        reference = self._investigations.document(investigation_id)
        for collection in _COLLECTIONS:
            self._delete_documents(reference.collection(collection).stream())
        reference.delete()

    def _delete_documents(self, documents: Iterable[Any]) -> None:
        for document in documents:
            document.reference.delete()
