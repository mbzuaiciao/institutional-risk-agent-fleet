"""Strict environment configuration for local and Google Cloud adapters."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CloudConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app_env: Literal["local", "cloud"] = "local"
    state_store: Literal["memory", "firestore"] = "memory"
    google_cloud_project: str | None = None
    firestore_database: str = "(default)"
    pubsub_topic: str | None = None
    worker_url: str | None = None
    reasoning_provider: Literal["offline", "gemini"] = "offline"
    deterministic_fallback: bool = False
    demo_reset_enabled: bool = True
    worker_auth: bool = True
    event_poll_seconds: float = Field(default=1.0, gt=0, le=10)
    event_poll_timeout_seconds: float = Field(default=90.0, gt=0, le=600)

    @model_validator(mode="after")
    def validate_cloud_requirements(self) -> CloudConfig:
        if self.state_store == "firestore" and not self.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore")
        if self.app_env == "cloud":
            missing = [
                name
                for name, value in (
                    ("GOOGLE_CLOUD_PROJECT", self.google_cloud_project),
                    ("PUBSUB_TOPIC", self.pubsub_topic),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"cloud configuration missing: {', '.join(missing)}")
        return self

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> CloudConfig:
        env = environment if environment is not None else os.environ
        return cls.model_validate(
            {
                "app_env": env.get("APP_ENV", "local"),
                "state_store": env.get("STATE_STORE", "memory"),
                "google_cloud_project": env.get("GOOGLE_CLOUD_PROJECT") or None,
                "firestore_database": env.get("FIRESTORE_DATABASE", "(default)"),
                "pubsub_topic": env.get("PUBSUB_TOPIC") or None,
                "worker_url": env.get("WORKER_URL") or None,
                "reasoning_provider": env.get("RISK_FLEET_PROVIDER", "offline"),
                "deterministic_fallback": _boolean(
                    env.get("RISK_FLEET_DETERMINISTIC_FALLBACK", "false")
                ),
                "demo_reset_enabled": _boolean(env.get("DEMO_RESET_ENABLED", "true")),
                "worker_auth": _boolean(env.get("WORKER_AUTH", "true")),
                "event_poll_seconds": float(env.get("EVENT_POLL_SECONDS", "1")),
                "event_poll_timeout_seconds": float(
                    env.get("EVENT_POLL_TIMEOUT_SECONDS", "90")
                ),
            }
        )

    @property
    def environment_label(self) -> str:
        return (
            "Google Cloud / Firestore"
            if self.app_env == "cloud" and self.state_store == "firestore"
            else "Local / In-memory"
        )


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"expected true or false, got {value!r}")
    return normalized == "true"
