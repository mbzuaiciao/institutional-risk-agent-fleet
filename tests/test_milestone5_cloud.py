from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from pydantic import ValidationError

from institutional_risk_fleet.cloud_api import create_app
from institutional_risk_fleet.cloud_config import CloudConfig
from institutional_risk_fleet.domain import (
    ClaimStatus,
    EventType,
    HumanAction,
    HumanReviewStatus,
    Investigation,
)
from institutional_risk_fleet.event_handler import (
    INVESTIGATION_ID,
    RiskEventApplication,
    RiskEventEnvelope,
)
from institutional_risk_fleet.firestore_store import (
    FirestoreStateStore,
    _create_firestore_client,
    deserialize_investigation,
    investigation_documents,
    serialize_investigation,
)
from institutional_risk_fleet.reasoning import OfflineReasoningProvider, ReasoningContext
from institutional_risk_fleet.store import InMemoryStateStore
from institutional_risk_fleet.ui_service import CloudDemoApplication
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


def event() -> RiskEventEnvelope:
    return RiskEventEnvelope(
        schema_version="1",
        event_id="risk-event-acme-001",
        scenario_id="acme-synthetic-v1",
    )


class CountingProvider(OfflineReasoningProvider):
    def __init__(self) -> None:
        self.calls = 0

    def run(self, context: ReasoningContext, observer=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().run(context, observer)


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[RiskEventEnvelope] = []

    def publish(self, envelope: RiskEventEnvelope) -> str:
        self.events.append(envelope)
        return "message-001"


class FakeWorkerApi:
    def __init__(self) -> None:
        self.store = InMemoryStateStore()
        self.application = RiskEventApplication(self.store, OfflineReasoningProvider())
        self.published = 0

    def publish_event(self) -> None:
        self.published += 1
        self.application.handle(event(), delivery_id=f"delivery-{self.published}")

    def get_investigation(self) -> Investigation | None:
        try:
            return self.store.get(INVESTIGATION_ID)
        except KeyError:
            return None

    def record_decision(
        self, *, action: HumanAction, reviewer: str, rationale: str
    ) -> Investigation:
        return DeterministicRiskWorkflow(store=self.store).record_human_decision(
            INVESTIGATION_ID, action=action, reviewer=reviewer, rationale=rationale
        )

    def reset_demo(self) -> None:
        self.store.reset_demo_event("risk-event-acme-001", INVESTIGATION_ID)


class FakeSnapshot:
    def __init__(self, reference, data):  # type: ignore[no-untyped-def]
        self.reference = reference
        self._data = data
        self.exists = data is not None

    def to_dict(self):  # type: ignore[no-untyped-def]
        return self._data.copy() if self._data is not None else None


class FakeDocument:
    def __init__(self, client, path):  # type: ignore[no-untyped-def]
        self.client = client
        self.path = path

    def get(self, transaction=None):  # type: ignore[no-untyped-def]
        return FakeSnapshot(self, self.client.data.get(self.path))

    def set(self, data):  # type: ignore[no-untyped-def]
        self.client.data[self.path] = data.copy()

    def update(self, data):  # type: ignore[no-untyped-def]
        current = self.client.data[self.path]
        for key, value in data.items():
            if value is self.client.delete_field:
                current.pop(key, None)
            else:
                current[key] = value

    def delete(self):  # type: ignore[no-untyped-def]
        self.client.data.pop(self.path, None)

    def collection(self, name):  # type: ignore[no-untyped-def]
        return FakeCollection(self.client, (*self.path, name))


class FakeCollection:
    def __init__(self, client, path):  # type: ignore[no-untyped-def]
        self.client = client
        self.path = path

    def document(self, document_id):  # type: ignore[no-untyped-def]
        return FakeDocument(self.client, (*self.path, document_id))

    def stream(self):  # type: ignore[no-untyped-def]
        return [
            FakeSnapshot(FakeDocument(self.client, path), data)
            for path, data in list(self.client.data.items())
            if path[:-1] == self.path
        ]


class FakeWriter:
    def set(self, reference, data):  # type: ignore[no-untyped-def]
        reference.set(data)

    def delete(self, reference):  # type: ignore[no-untyped-def]
        reference.delete()

    def commit(self) -> None:
        return None


class FakeFirestoreClient:
    def __init__(self, delete_field) -> None:  # type: ignore[no-untyped-def]
        self.data: dict[tuple[str, ...], dict[str, object]] = {}
        self.delete_field = delete_field

    def collection(self, name):  # type: ignore[no-untyped-def]
        return FakeCollection(self, (name,))

    def transaction(self):  # type: ignore[no-untyped-def]
        return FakeWriter()

    def batch(self):  # type: ignore[no-untyped-def]
        return FakeWriter()


def test_firestore_serialization_preserves_history_and_audit_order() -> None:
    investigation = DeterministicRiskWorkflow().run()
    restored = deserialize_investigation(serialize_investigation(investigation))
    documents = investigation_documents(restored)

    assert restored == investigation
    assert dict(documents["claims"])["claim-001"]["status"] == ClaimStatus.REJECTED.value
    assert dict(documents["claims"])["claim-002"]["supersedes_claim_id"] == "claim-001"
    assert [item[1]["sequence"] for item in documents["audit_events"]] == list(
        range(1, len(investigation.audit_events) + 1)
    )


def test_in_memory_store_contract_is_copy_safe_and_atomic() -> None:
    store = InMemoryStateStore()
    investigation = DeterministicRiskWorkflow(store=store).run()
    detached = store.get(investigation.id)
    detached.revision_count = 99
    assert store.get(investigation.id).revision_count == 1

    updated = store.update_atomically(
        investigation.id,
        lambda value: value.model_copy(update={"revision_count": 2}),
    )
    assert updated.revision_count == store.get(investigation.id).revision_count == 2


def test_firestore_store_contract_matches_memory_with_fake_client(monkeypatch) -> None:
    import institutional_risk_fleet.firestore_store as module

    monkeypatch.setattr(module.firestore, "transactional", lambda function: function)
    client = FakeFirestoreClient(module.firestore.DELETE_FIELD)
    store = FirestoreStateStore(project="test-project", client=client)
    assert not hasattr(client, "_database_string_internal")
    investigation = DeterministicRiskWorkflow().run()

    store.create(investigation)
    assert store.get(investigation.id) == investigation
    updated = store.update_atomically(
        investigation.id,
        lambda value: value.model_copy(update={"revision_count": 2}),
    )
    assert updated.revision_count == store.get(investigation.id).revision_count == 2
    claim_paths = [path for path in client.data if "claims" in path]
    assert ("investigations", INVESTIGATION_ID, "claims", "claim-001") in claim_paths
    assert ("investigations", INVESTIGATION_ID, "claims", "claim-002") in claim_paths
    store.reset_demo_event("risk-event-acme-001", INVESTIGATION_ID)
    with pytest.raises(KeyError):
        store.get(INVESTIGATION_ID)


def test_pinned_firestore_default_database_compatibility_is_narrow(monkeypatch) -> None:
    client_type = firestore.Client
    default_client = client_type(
        project="test-project",
        database="(default)",
        credentials=AnonymousCredentials(),
    )
    assert "%28default%29" in default_client._database_string
    monkeypatch.setattr(
        "institutional_risk_fleet.firestore_store.firestore.Client",
        lambda **_kwargs: default_client,
    )
    fixed = _create_firestore_client(project="test-project", database="(default)")
    assert fixed._database_string == "projects/test-project/databases/(default)"

    named_client = client_type(
        project="test-project",
        database="named-db",
        credentials=AnonymousCredentials(),
    )
    monkeypatch.setattr(
        "institutional_risk_fleet.firestore_store.firestore.Client",
        lambda **_kwargs: named_client,
    )
    untouched = _create_firestore_client(project="test-project", database="named-db")
    assert untouched._database_string == "projects/test-project/databases/named-db"


def test_duplicate_delivery_runs_reasoning_once_and_reuses_investigation() -> None:
    store = InMemoryStateStore()
    provider = CountingProvider()
    application = RiskEventApplication(store, provider)

    first = application.handle(event(), delivery_id="message-001")
    duplicate = application.handle(event(), delivery_id="message-002")

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.investigation == first.investigation
    assert provider.calls == 1
    assert len(duplicate.investigation.claims) == len(first.investigation.claims)  # type: ignore[union-attr]


def test_reset_refuses_to_race_an_active_event() -> None:
    store = InMemoryStateStore()
    store.reserve_event("risk-event-acme-001", INVESTIGATION_ID, "message-active")
    with pytest.raises(ValueError, match="processing is active"):
        store.reset_demo_event("risk-event-acme-001", INVESTIGATION_ID)


def test_event_schema_and_known_fixture_validation() -> None:
    with pytest.raises(ValidationError):
        RiskEventEnvelope.model_validate(
            {"schema_version": "2", "event_id": "x", "scenario_id": "y", "amount": 12}
        )
    with pytest.raises(ValueError, match="unknown"):
        RiskEventApplication(InMemoryStateStore(), OfflineReasoningProvider()).handle(
            RiskEventEnvelope(schema_version="1", event_id="unknown", scenario_id="unknown"),
            delivery_id="message-bad",
        )


def test_pubsub_http_handler_delegates_to_existing_workflow() -> None:
    store = InMemoryStateStore()
    provider = CountingProvider()
    publisher = FakePublisher()
    app = create_app(
        config=CloudConfig(), store=store, provider=provider, publisher=publisher
    )
    client = TestClient(app)
    payload = base64.b64encode(event().model_dump_json().encode()).decode()

    response = client.post(
        "/pubsub/push",
        json={"message": {"data": payload, "messageId": "message-001"}},
    )
    duplicate = client.post(
        "/pubsub/push",
        json={"message": {"data": payload, "messageId": "message-002"}},
    )

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert provider.calls == 1
    assert store.get(INVESTIGATION_ID).human_review_status == HumanReviewStatus.REQUIRED


def test_pubsub_http_rejects_malformed_payload_and_publish_is_narrow() -> None:
    publisher = FakePublisher()
    client = TestClient(create_app(config=CloudConfig(), publisher=publisher))
    assert client.post(
        "/pubsub/push", json={"message": {"data": "not-base64", "messageId": "bad"}}
    ).status_code == 400
    assert client.post("/events", json=event().model_dump(mode="json")).status_code == 202
    assert publisher.events == [event()]
    assert client.post(
        "/events",
        json={"schema_version": "1", "event_id": "other", "scenario_id": "other"},
    ).status_code == 400


def test_pubsub_transport_extras_are_ignored_but_cannot_override_payload() -> None:
    store = InMemoryStateStore()
    client = TestClient(
        create_app(
            config=CloudConfig(),
            store=store,
            provider=OfflineReasoningProvider(),
            publisher=FakePublisher(),
        )
    )
    payload = base64.b64encode(event().model_dump_json().encode()).decode()
    response = client.post(
        "/pubsub/push",
        json={
            "message": {
                "data": payload,
                "messageId": "message-with-metadata",
                "publishTime": "2026-08-24T12:00:00Z",
                "attributes": {
                    "event_id": "another-event",
                    "override_governance": "true",
                },
                "orderingKey": "acme",
            },
            "subscription": "projects/test/subscriptions/risk-events",
            "deliveryAttempt": 2,
        },
    )
    assert response.status_code == 200
    assert store.get(INVESTIGATION_ID).event.id == "risk-event-acme-001"


def test_pubsub_decoded_application_payload_remains_strict() -> None:
    client = TestClient(create_app(config=CloudConfig(), publisher=FakePublisher()))
    payload = base64.b64encode(
        b'{"schema_version":"1","event_id":"risk-event-acme-001",'
        b'"scenario_id":"acme-synthetic-v1","override_governance":true}'
    ).decode()
    response = client.post(
        "/pubsub/push",
        json={"message": {"data": payload, "messageId": "message-malicious"}},
    )
    assert response.status_code == 400
    assert "override_governance" in response.json()["detail"]


def test_concurrent_terminal_human_decisions_first_wins_and_second_is_audited() -> None:
    store = InMemoryStateStore()
    workflow = DeterministicRiskWorkflow(store=store)
    workflow.run()

    def decide(action: HumanAction) -> str:
        try:
            workflow.record_human_decision(
                INVESTIGATION_ID,
                action=action,
                reviewer="Risk Officer",
                rationale="Reviewed deterministic evidence.",
            )
        except ValueError as error:
            return str(error)
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(decide, (HumanAction.APPROVE, HumanAction.REJECT)))

    final = store.get(INVESTIGATION_ID)
    assert sorted(outcomes) == ["accepted", "investigation is not awaiting human review"]
    assert len(final.human_decisions) == 1
    assert final.lifecycle_status.value == "COMPLETED"
    assert final.audit_events[-1].event_type == EventType.HUMAN_DECISION_REJECTED


def test_cloud_ui_uses_async_api_contract_and_persistent_decision() -> None:
    api = FakeWorkerApi()
    config = CloudConfig(
        app_env="cloud",
        state_store="firestore",
        google_cloud_project="test-project",
        pubsub_topic="risk-events",
        worker_url="https://worker.example",
        event_poll_seconds=0.01,
    )
    service = CloudDemoApplication(api, config)

    investigation = service.trigger()
    assert api.published == 1
    assert investigation.id == INVESTIGATION_ID
    completed = service.record_human_decision(
        action=HumanAction.APPROVE,
        reviewer="Risk Officer",
        rationale="Reviewed correction.",
    )
    assert completed.human_review_status == HumanReviewStatus.APPROVED
    assert service.current_investigation() == completed


def test_cloud_configuration_validation_and_labels() -> None:
    assert CloudConfig.from_env({}).environment_label == "Local / In-memory"
    with pytest.raises(ValidationError, match="GOOGLE_CLOUD_PROJECT"):
        CloudConfig.from_env({"APP_ENV": "cloud", "STATE_STORE": "firestore"})
    cloud = CloudConfig.from_env(
        {
            "APP_ENV": "cloud",
            "STATE_STORE": "firestore",
            "GOOGLE_CLOUD_PROJECT": "test-project",
            "PUBSUB_TOPIC": "risk-events",
        }
    )
    assert cloud.environment_label == "Google Cloud / Firestore"
