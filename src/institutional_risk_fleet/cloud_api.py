"""Cloud Run worker/API with authenticated Pub/Sub push and narrow UI actions."""

from __future__ import annotations

import base64
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Response, status
from google.cloud import pubsub_v1
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from institutional_risk_fleet.adk_provider import configured_gemini_provider
from institutional_risk_fleet.cloud_config import CloudConfig
from institutional_risk_fleet.domain import HumanAction, Investigation
from institutional_risk_fleet.event_handler import (
    EVENT_ID,
    INVESTIGATION_ID,
    RiskEventApplication,
    RiskEventEnvelope,
)
from institutional_risk_fleet.firestore_store import FirestoreStateStore
from institutional_risk_fleet.reasoning import OfflineReasoningProvider, ReasoningProvider
from institutional_risk_fleet.store import InMemoryStateStore, StateStore
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


class PubSubMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    data: str
    message_id: str = Field(alias="messageId")


class PubSubPushEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message: PubSubMessage
    subscription: str | None = None


class HumanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: HumanAction
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class EventPublisher(Protocol):
    def publish(self, envelope: RiskEventEnvelope) -> str: ...


class GooglePubSubPublisher:
    def __init__(self, project: str, topic: str, client: Any | None = None) -> None:
        self._client = client or pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project, topic)

    def publish(self, envelope: RiskEventEnvelope) -> str:
        future = self._client.publish(
            self._topic_path,
            envelope.model_dump_json().encode("utf-8"),
            schema_version=envelope.schema_version,
            event_id=envelope.event_id,
        )
        return str(future.result(timeout=15))


def create_app(
    *,
    config: CloudConfig | None = None,
    store: StateStore | None = None,
    provider: ReasoningProvider | None = None,
    publisher: EventPublisher | None = None,
) -> FastAPI:
    selected = config or CloudConfig.from_env()
    state_store = store or _build_store(selected)
    reasoning_provider = provider or _build_provider(selected)
    event_application = RiskEventApplication(state_store, reasoning_provider)
    event_publisher = publisher or _build_publisher(selected)
    app = FastAPI(title="Institutional Risk Agent Fleet API", version="1")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": selected.environment_label}

    @app.post("/pubsub/push")
    def pubsub_push(push: PubSubPushEnvelope, response: Response) -> dict[str, object]:
        try:
            raw = base64.b64decode(push.message.data, validate=True)
            envelope = RiskEventEnvelope.model_validate_json(raw)
            result = event_application.handle(envelope, delivery_id=push.message.message_id)
        except (ValueError, ValidationError, UnicodeDecodeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        response.status_code = status.HTTP_200_OK
        return {
            "accepted": True,
            "duplicate": result.duplicate,
            "status": result.status,
            "investigation_id": result.investigation.id if result.investigation else INVESTIGATION_ID,
        }

    @app.post("/events", status_code=status.HTTP_202_ACCEPTED)
    def publish_event(envelope: RiskEventEnvelope) -> dict[str, str]:
        try:
            RiskEventApplication._validate_known_event(envelope)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if event_publisher is None:
            raise HTTPException(status_code=503, detail="Pub/Sub publisher is not configured")
        try:
            message_id = event_publisher.publish(envelope)
        except Exception as error:
            raise HTTPException(status_code=503, detail="event publication failed") from error
        return {"status": "published", "message_id": message_id, "event_id": envelope.event_id}

    @app.get("/investigations/{investigation_id}", response_model=Investigation)
    def get_investigation(investigation_id: str) -> Investigation:
        try:
            return state_store.get(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/investigations/{investigation_id}/decisions", response_model=Investigation)
    def record_decision(
        investigation_id: str, decision: HumanDecisionRequest
    ) -> Investigation:
        workflow = DeterministicRiskWorkflow(
            store=state_store, reasoning_provider=reasoning_provider
        )
        try:
            return workflow.record_human_decision(
                investigation_id,
                action=decision.action,
                reviewer=decision.reviewer,
                rationale=decision.rationale,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, ValidationError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/demo/reset")
    def reset_demo() -> dict[str, str]:
        if not selected.demo_reset_enabled:
            raise HTTPException(status_code=403, detail="demo reset is disabled")
        try:
            state_store.reset_demo_event(EVENT_ID, INVESTIGATION_ID)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "reset", "event_id": EVENT_ID, "investigation_id": INVESTIGATION_ID}

    return app


def _build_store(config: CloudConfig) -> StateStore:
    if config.state_store == "memory":
        return InMemoryStateStore()
    assert config.google_cloud_project is not None
    return FirestoreStateStore(
        project=config.google_cloud_project, database=config.firestore_database
    )


def _build_provider(config: CloudConfig) -> ReasoningProvider:
    if config.reasoning_provider == "offline":
        return OfflineReasoningProvider()
    return configured_gemini_provider(
        deterministic_fallback=config.deterministic_fallback
    )


def _build_publisher(config: CloudConfig) -> EventPublisher | None:
    if not config.google_cloud_project or not config.pubsub_topic:
        return None
    return GooglePubSubPublisher(config.google_cloud_project, config.pubsub_topic)


app = create_app()
