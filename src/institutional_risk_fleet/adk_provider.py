"""Google ADK orchestration for bounded, typed Gemini reasoning."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from institutional_risk_fleet.domain import EventType, ModelCallRecord, Role
from institutional_risk_fleet.reasoning import (
    ChallengeOutput,
    CreditAnalysis,
    InvestigationSynthesis,
    MarketAnalysis,
    ModelObserver,
    OfflineReasoningProvider,
    ProviderOutcome,
    ReasoningBundle,
    ReasoningContext,
    ReasoningProvider,
    ReasoningProviderError,
)

PROMPT_VERSIONS: dict[Role, str] = {
    Role.CREDIT: "credit-v1",
    Role.MARKET: "market-v1",
    Role.INVESTIGATOR: "investigator-v1",
    Role.CHALLENGER: "challenger-v1",
}
DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"


@dataclass(frozen=True, slots=True)
class GeminiReasoningConfig:
    model_id: str = DEFAULT_GEMINI_MODEL
    timeout_seconds: float = 60.0
    retries: int = 1
    deterministic_fallback: bool = False

    @classmethod
    def from_env(cls, *, deterministic_fallback: bool | None = None) -> GeminiReasoningConfig:
        fallback = (
            os.getenv("RISK_FLEET_DETERMINISTIC_FALLBACK", "false").lower() == "true"
            if deterministic_fallback is None
            else deterministic_fallback
        )
        return cls(
            model_id=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "60")),
            retries=int(os.getenv("GEMINI_MAX_RETRIES", "1")),
            deterministic_fallback=fallback,
        )


class ProviderAttemptError(ReasoningProviderError):
    def __init__(self, message: str, records: tuple[ModelCallRecord, ...]) -> None:
        super().__init__(message)
        self.records = records


def _prompt(role: Role) -> str:
    path = Path(__file__).with_name("prompts") / f"{role.value}.md"
    return path.read_text(encoding="utf-8")


def build_adk_pipeline(model_id: str) -> SequentialAgent:
    """Build Credit+Market in parallel, followed by Investigator and Challenger."""
    model = Gemini(model=model_id, retry_options=types.HttpRetryOptions(attempts=1))
    credit = Agent(
        name=Role.CREDIT.value,
        model=model,
        instruction=_prompt(Role.CREDIT),
        output_schema=CreditAnalysis,
        output_key="credit_analysis",
    )
    market = Agent(
        name=Role.MARKET.value,
        model=model,
        instruction=_prompt(Role.MARKET),
        output_schema=MarketAnalysis,
        output_key="market_analysis",
    )
    investigator = Agent(
        name=Role.INVESTIGATOR.value,
        model=model,
        instruction=_prompt(Role.INVESTIGATOR),
        output_schema=InvestigationSynthesis,
        output_key="investigation_synthesis",
    )
    challenger = Agent(
        name=Role.CHALLENGER.value,
        model=model,
        instruction=_prompt(Role.CHALLENGER),
        output_schema=ChallengeOutput,
        output_key="challenge_output",
    )
    parallel = ParallelAgent(name="credit_market_parallel", sub_agents=[credit, market])
    return SequentialAgent(
        name="institutional_risk_reasoning",
        sub_agents=[parallel, investigator, challenger],
    )


class GeminiAdkProvider:
    name = "gemini"

    def __init__(self, config: GeminiReasoningConfig | None = None) -> None:
        self.config = config or GeminiReasoningConfig.from_env()
        self.model_id = self.config.model_id
        self.root_agent = build_adk_pipeline(self.model_id)

    def run(
        self, context: ReasoningContext, observer: ModelObserver | None = None
    ) -> ProviderOutcome:
        return asyncio.run(self._run(context, observer))

    async def _run(
        self, context: ReasoningContext, observer: ModelObserver | None
    ) -> ProviderOutcome:
        roles = (Role.CREDIT, Role.MARKET, Role.INVESTIGATOR, Role.CHALLENGER)
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        request_ids = {role: f"gemini-{uuid4()}" for role in roles}
        for role in roles:
            _observe(
                observer,
                EventType.MODEL_REQUEST_STARTED,
                role,
                request_ids[role],
                model_id=self.model_id,
                prompt_version=PROMPT_VERSIONS[role],
            )
        usage: dict[Role, tuple[int | None, int | None, int | None]] = {}
        try:
            service = InMemorySessionService()
            app_name = "institutional_risk_agent_fleet"
            user_id = "system"
            session_id = context.investigation_id
            await service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state={"scenario_context": context.model_dump_json()},
            )
            runner = Runner(
                app_name=app_name,
                agent=self.root_agent,
                session_service=service,
            )

            async def consume() -> None:
                content = types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Run the governed risk reasoning sequence.")],
                )
                async for event in runner.run_async(
                    user_id=user_id, session_id=session_id, new_message=content
                ):
                    try:
                        role = Role(event.author)
                    except ValueError:
                        continue
                    metadata = event.usage_metadata
                    if metadata is not None:
                        usage[role] = (
                            metadata.prompt_token_count,
                            metadata.candidates_token_count,
                            metadata.total_token_count,
                        )

            await asyncio.wait_for(consume(), timeout=self.config.timeout_seconds)
            session = await service.get_session(
                app_name=app_name, user_id=user_id, session_id=session_id
            )
            if session is None:
                raise ReasoningProviderError("ADK session disappeared before output collection")
            state = session.state
            bundle = ReasoningBundle(
                credit=_parse_output(state.get("credit_analysis"), CreditAnalysis),
                market=_parse_output(state.get("market_analysis"), MarketAnalysis),
                investigation=_parse_output(
                    state.get("investigation_synthesis"), InvestigationSynthesis
                ),
                challenger=_parse_output(state.get("challenge_output"), ChallengeOutput),
            )
        except (ValidationError, ValueError, TypeError, KeyError) as error:
            validation_error_type = (
                "empty_result" if "empty ADK output" in str(error) else "malformed_structured_output"
            )
            records = _records(
                roles,
                request_ids,
                self.model_id,
                started_at,
                started_clock,
                usage,
                validation_error_type,
            )
            for role in roles:
                _observe(
                    observer,
                    EventType.MODEL_OUTPUT_VALIDATION_FAILED,
                    role,
                    request_ids[role],
                    error_type=validation_error_type,
                )
            raise ProviderAttemptError("Gemini returned invalid structured output", records) from error
        except TimeoutError as error:
            records = _records(
                roles, request_ids, self.model_id, started_at, started_clock, usage, "timeout"
            )
            raise ProviderAttemptError("Gemini reasoning timed out", records) from error
        except Exception as error:
            provider_error_type = _classify_provider_error(error)
            records = _records(
                roles,
                request_ids,
                self.model_id,
                started_at,
                started_clock,
                usage,
                provider_error_type,
            )
            raise ProviderAttemptError(
                f"Gemini provider failed: {type(error).__name__}", records
            ) from error

        records = _records(roles, request_ids, self.model_id, started_at, started_clock, usage, None)
        for record in records:
            _observe(
                observer,
                EventType.MODEL_RESPONSE_RECEIVED,
                record.role,
                record.request_id,
                latency_ms=record.latency_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                total_tokens=record.total_tokens,
            )
            _observe(
                observer,
                EventType.MODEL_ROLE_COMPLETED,
                record.role,
                record.request_id,
                validation_status="valid",
            )
        return ProviderOutcome(
            bundle=bundle,
            provider=self.name,
            model_id=self.model_id,
            model_calls=records,
        )


class ResilientReasoningProvider:
    """Bound retries and make deterministic fallback an explicit, observable choice."""

    def __init__(
        self,
        primary: ReasoningProvider,
        *,
        max_retries: int,
        fallback: OfflineReasoningProvider | None = None,
    ) -> None:
        self.primary = primary
        self.max_retries = max(0, max_retries)
        self.fallback = fallback
        self.name = primary.name
        self.model_id = primary.model_id

    def run(
        self, context: ReasoningContext, observer: ModelObserver | None = None
    ) -> ProviderOutcome:
        records: list[ModelCallRecord] = []
        for attempt in range(self.max_retries + 1):
            try:
                outcome = self.primary.run(context, observer)
                adjusted = tuple(
                    record.model_copy(update={"retry_count": attempt})
                    for record in outcome.model_calls
                )
                return outcome.model_copy(update={"model_calls": tuple(records) + adjusted})
            except ProviderAttemptError as error:
                records.extend(
                    record.model_copy(update={"retry_count": attempt}) for record in error.records
                )
                _observe(
                    observer,
                    EventType.MODEL_PROVIDER_FAILED,
                    Role.ORCHESTRATOR,
                    None,
                    provider=self.name,
                    error_type=(
                        error.records[0].error_type
                        if error.records
                        else type(error.__cause__).__name__
                        if error.__cause__
                        else type(error).__name__
                    ),
                    attempt=attempt + 1,
                )
                if attempt < self.max_retries:
                    _observe(
                        observer,
                        EventType.MODEL_RETRY,
                        Role.ORCHESTRATOR,
                        None,
                        provider=self.name,
                        next_attempt=attempt + 2,
                    )
                    continue
                if self.fallback is None:
                    error.records = tuple(records)
                    raise
        fallback = self.fallback
        if fallback is None:
            raise ReasoningProviderError("provider failed without a configured fallback")
        fallback_outcome = fallback.run(context, observer)
        _observe(
            observer,
            EventType.MODEL_FALLBACK_USED,
            Role.ORCHESTRATOR,
            None,
            failed_provider=self.name,
            fallback_provider=fallback.name,
        )
        return fallback_outcome.model_copy(
            update={
                "provider": self.name,
                "model_id": self.model_id,
                "model_calls": tuple(
                    record.model_copy(update={"fallback_used": True}) for record in records
                ),
                "fallback_used": True,
            }
        )


def configured_gemini_provider(
    *, deterministic_fallback: bool | None = None
) -> ResilientReasoningProvider:
    config = GeminiReasoningConfig.from_env(
        deterministic_fallback=deterministic_fallback
    )
    primary = GeminiAdkProvider(config)
    fallback = OfflineReasoningProvider() if config.deterministic_fallback else None
    return ResilientReasoningProvider(
        primary, max_retries=config.retries, fallback=fallback
    )


def _parse_output(value: Any, model: type[Any]) -> Any:
    if value is None or value == "":
        raise ValueError(f"empty ADK output for {model.__name__}")
    if isinstance(value, str):
        return model.model_validate_json(value)
    if isinstance(value, dict):
        return model.model_validate(value)
    if isinstance(value, model):
        return value
    return model.model_validate(json.loads(str(value)))


def _classify_provider_error(error: Exception) -> str:
    name = type(error).__name__.lower()
    message = str(error).lower()
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status == 429 or "rate limit" in message or "resourceexhausted" in name:
        return "rate_limit"
    if status == 503 or any(
        marker in name or marker in message
        for marker in ("unavailable", "connection", "transport")
    ):
        return "provider_unavailable"
    return f"provider_error:{type(error).__name__}"


def _records(
    roles: tuple[Role, ...],
    request_ids: dict[Role, str],
    model_id: str,
    started_at: datetime,
    started_clock: float,
    usage: dict[Role, tuple[int | None, int | None, int | None]],
    error_type: str | None,
) -> tuple[ModelCallRecord, ...]:
    ended_at = datetime.now(UTC)
    latency = (perf_counter() - started_clock) * 1000
    return tuple(
        ModelCallRecord(
            id=f"model-call-{request_ids[role]}",
            role=role,
            provider="gemini",
            model_id=model_id,
            prompt_version=PROMPT_VERSIONS[role],
            request_id=request_ids[role],
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency,
            validation_status="invalid" if error_type else "valid",
            input_tokens=usage.get(role, (None, None, None))[0],
            output_tokens=usage.get(role, (None, None, None))[1],
            total_tokens=usage.get(role, (None, None, None))[2],
            error_type=error_type,
        )
        for role in roles
    )


def _observe(
    observer: ModelObserver | None,
    event_type: EventType,
    role: Role,
    request_id: str | None,
    **details: Any,
) -> None:
    if observer is not None:
        observer(event_type, role, request_id, details)
