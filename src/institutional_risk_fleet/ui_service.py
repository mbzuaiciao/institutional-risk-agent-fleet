"""Thin application service and view models for the judge-facing Streamlit UI."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from pydantic import BaseModel, ConfigDict

from institutional_risk_fleet.adk_provider import configured_gemini_provider
from institutional_risk_fleet.cloud_config import CloudConfig
from institutional_risk_fleet.domain import (
    Claim,
    ClaimStatus,
    EventType,
    FindingResult,
    HumanAction,
    Investigation,
    LifecycleStatus,
    Role,
    Task,
    TaskStatus,
)
from institutional_risk_fleet.reasoning import OfflineReasoningProvider
from institutional_risk_fleet.scenario import load_default_scenario
from institutional_risk_fleet.store import InMemoryStateStore
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow

INVESTIGATION_ID = "investigation-acme-001"


class ViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderAvailability(ViewModel):
    provider: str
    available: bool
    reason: str


class PortfolioRow(ViewModel):
    issuer: str
    market_value_usd: float
    spread_duration: float


class PortfolioView(ViewModel):
    issuer: str
    exposure_usd: float
    previous_spread_bps: float
    current_spread_bps: float
    spread_move_bps: float
    severity: str
    lifecycle: str
    governance: str
    positions: tuple[PortfolioRow, ...]


class ProgressItem(ViewModel):
    label: str
    execution_type: str
    status: str
    result: str


class InvestigationView(ViewModel):
    reasoning_label: str
    configured_model_id: str | None
    progress: tuple[ProgressItem, ...]


class SupportValue(ViewModel):
    label: str
    value: float | str
    unit: str
    authoritative: bool
    reference_id: str


class ClaimHistoryItem(ViewModel):
    claim_id: str
    text: str
    value: float | str | None
    unit: str | None
    status: str
    supersedes_claim_id: str | None
    evidence_ids: tuple[str, ...]
    tool_execution_ids: tuple[str, ...]


class PermissionDenial(ViewModel):
    actor: str
    capability: str
    rationale: str
    sequence: int


class VerificationView(ViewModel):
    rejected_claim: ClaimHistoryItem | None
    revised_claim: ClaimHistoryItem | None
    support_values: tuple[SupportValue, ...]
    failure_rationale: str | None
    permission_denial: PermissionDenial | None


class DecisionView(ViewModel):
    machine_verification: str
    risk_classification: str
    governance_status: str
    human_review_status: str
    lifecycle_status: str
    recommendation: str | None
    supporting_premises: tuple[str, ...]
    decision_recorded: bool


class AuditItem(ViewModel):
    sequence: int
    actor: str
    event_type: str
    summary: str


class GeminiUnavailableError(RuntimeError):
    pass


class DecisionInputError(ValueError):
    pass


class WorkerApi(Protocol):
    def publish_event(self) -> None: ...

    def get_investigation(self) -> Investigation | None: ...

    def record_decision(
        self, *, action: HumanAction, reviewer: str, rationale: str
    ) -> Investigation: ...

    def reset_demo(self) -> None: ...


def gemini_availability(
    environment: Mapping[str, str] | None = None,
    *,
    default_adc_path: Path | None = None,
) -> ProviderAvailability:
    env = environment if environment is not None else os.environ
    if env.get("GEMINI_API_KEY", "").strip() or env.get("GOOGLE_API_KEY", "").strip():
        return ProviderAvailability(
            provider="gemini", available=True, reason="Gemini API credential detected."
        )
    vertex_enabled = env.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() == "true"
    project = env.get("GOOGLE_CLOUD_PROJECT", "").strip()
    explicit_credentials = env.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    explicit_exists = bool(explicit_credentials and Path(explicit_credentials).is_file())
    adc_path = default_adc_path or Path.home() / ".config/gcloud/application_default_credentials.json"
    if vertex_enabled and project and (explicit_exists or adc_path.is_file()):
        return ProviderAvailability(
            provider="gemini", available=True, reason="Vertex AI credential chain detected."
        )
    return ProviderAvailability(
        provider="gemini",
        available=False,
        reason=(
            "Configure GEMINI_API_KEY (or GOOGLE_API_KEY), or enable Vertex AI with a project "
            "and Application Default Credentials."
        ),
    )


class DemoApplication:
    """Idempotent controller over the existing workflow and authoritative store."""

    def __init__(
        self,
        *,
        provider_name: str = "offline",
        deterministic_fallback: bool = False,
        environment: Mapping[str, str] | None = None,
        default_adc_path: Path | None = None,
    ) -> None:
        if provider_name not in {"offline", "gemini"}:
            raise ValueError(f"unsupported provider: {provider_name}")
        self.provider_name = provider_name
        self.deterministic_fallback = deterministic_fallback
        self.environment = environment
        self.default_adc_path = default_adc_path
        self.scenario = load_default_scenario()
        self._store = InMemoryStateStore()
        self._workflow: DeterministicRiskWorkflow | None = None
        self._triggered = False

    @property
    def triggered(self) -> bool:
        return self._triggered

    def reset(self) -> PortfolioView:
        self.scenario = load_default_scenario()
        self._store = InMemoryStateStore()
        self._workflow = None
        self._triggered = False
        return self.portfolio_view()

    def trigger(self) -> Investigation:
        if self._triggered:
            return self._store.get(INVESTIGATION_ID)
        provider = self._build_provider()
        self._workflow = DeterministicRiskWorkflow(
            store=self._store, reasoning_provider=provider
        )
        investigation = self._workflow.run(self.scenario)
        self._triggered = True
        return investigation

    def current_investigation(self) -> Investigation | None:
        if not self._triggered:
            return None
        return self._store.get(INVESTIGATION_ID)

    def record_human_decision(
        self,
        *,
        action: HumanAction,
        reviewer: str,
        rationale: str,
    ) -> Investigation:
        reviewer = reviewer.strip()
        rationale = rationale.strip()
        if not reviewer:
            raise DecisionInputError("Reviewer identity is required.")
        if not rationale:
            raise DecisionInputError("Decision rationale is required.")
        if not self._triggered or self._workflow is None:
            raise DecisionInputError("Trigger the risk event before recording a decision.")
        return self._workflow.record_human_decision(
            INVESTIGATION_ID,
            action=action,
            reviewer=reviewer,
            rationale=rationale,
        )

    def portfolio_view(self) -> PortfolioView:
        investigation = self.current_investigation()
        event = self.scenario.event
        return PortfolioView(
            issuer=event.issuer_name,
            exposure_usd=event.portfolio_exposure_usd,
            previous_spread_bps=event.previous_spread_bps,
            current_spread_bps=event.current_spread_bps,
            spread_move_bps=event.spread_move_bps,
            severity=event.severity.value,
            lifecycle=(
                investigation.lifecycle_status.value if investigation else "NOT_TRIGGERED"
            ),
            governance=(investigation.governance_status.value if investigation else "PENDING"),
            positions=tuple(
                PortfolioRow(
                    issuer=position.issuer_name,
                    market_value_usd=position.market_value_usd,
                    spread_duration=position.spread_duration,
                )
                for position in self.scenario.positions
            ),
        )

    def investigation_view(self) -> InvestigationView | None:
        investigation = self.current_investigation()
        if investigation is None:
            return None
        task_by_role = {task.role: task for task in investigation.tasks.values()}
        claims_by_role = {
            role: [claim for claim in investigation.claims.values() if claim.author == role]
            for role in (Role.CREDIT, Role.MARKET, Role.INVESTIGATOR)
        }
        findings_passed = sum(
            finding.result == FindingResult.PASSED
            for finding in investigation.verification_findings
        )
        findings_failed = sum(
            finding.result == FindingResult.FAILED
            for finding in investigation.verification_findings
        )
        reasoning_label = (
            f"Gemini {investigation.configured_model_id} via Google ADK"
            if investigation.reasoning_provider == "gemini"
            else "Deterministic offline provider"
        )
        progress = (
            ProgressItem(
                label="Evidence Service",
                execution_type="Deterministic control",
                status=_task_status(task_by_role, Role.EVIDENCE),
                result=f"{len(investigation.evidence)} registered evidence objects",
            ),
            ProgressItem(
                label="Credit Agent",
                execution_type="Model-backed reasoning",
                status=_task_status(task_by_role, Role.CREDIT),
                result=_claim_summary(claims_by_role[Role.CREDIT]),
            ),
            ProgressItem(
                label="Market Agent",
                execution_type="Model-backed reasoning",
                status=_task_status(task_by_role, Role.MARKET),
                result=_claim_summary(claims_by_role[Role.MARKET]),
            ),
            ProgressItem(
                label="Investigator",
                execution_type="Model-backed reasoning",
                status=_task_status(task_by_role, Role.INVESTIGATOR),
                result=(
                    investigation.theses[investigation.active_thesis_id].primary_hypothesis
                    if investigation.active_thesis_id
                    else "No validated thesis entered state"
                ),
            ),
            ProgressItem(
                label="Challenger",
                execution_type="Model-backed reasoning",
                status=_task_status(task_by_role, Role.CHALLENGER),
                result=f"{len(investigation.challenges)} non-binding challenge(s)",
            ),
            ProgressItem(
                label="Verifier",
                execution_type="Deterministic control",
                status=_task_status(task_by_role, Role.VERIFIER),
                result=f"{findings_passed} passed / {findings_failed} failed findings retained",
            ),
            ProgressItem(
                label="Governance Engine",
                execution_type="Deterministic control",
                status=investigation.governance_status.value,
                result="Machine clearance and human-review policy evaluated separately",
            ),
        )
        return InvestigationView(
            reasoning_label=reasoning_label,
            configured_model_id=investigation.configured_model_id,
            progress=progress,
        )

    def verification_view(self) -> VerificationView | None:
        investigation = self.current_investigation()
        if investigation is None:
            return None
        leverage_claims = sorted(
            (
                claim
                for claim in investigation.claims.values()
                if claim.metric == "fy2025_leverage"
            ),
            key=lambda claim: claim.id,
        )
        rejected = next(
            (claim for claim in leverage_claims if claim.status == ClaimStatus.REJECTED), None
        )
        revised = next(
            (
                claim
                for claim in leverage_claims
                if claim.supersedes_claim_id is not None
                and claim.status == ClaimStatus.VERIFIED
            ),
            None,
        )
        if revised is None:
            revised = next(
                (claim for claim in leverage_claims if claim.status == ClaimStatus.VERIFIED), None
            )
        filing = investigation.evidence["evidence-filing-001"]
        upstream = investigation.evidence["evidence-upstream-001"]
        leverage_tool = next(
            execution
            for execution in investigation.tool_executions.values()
            if execution.tool_name == "leverage_ratio"
        )
        failure = next(
            (
                finding
                for finding in investigation.verification_findings
                if rejected is not None
                and finding.target_claim_id == rejected.id
                and finding.result == FindingResult.FAILED
            ),
            None,
        )
        denial_event = next(
            (
                event
                for event in investigation.audit_events
                if event.event_type == EventType.PERMISSION_DENIED
                and event.actor == Role.CREDIT
            ),
            None,
        )
        return VerificationView(
            rejected_claim=_claim_history(rejected),
            revised_claim=_claim_history(revised),
            support_values=(
                SupportValue(
                    label="Upstream enrichment",
                    value=upstream.facts["fy2025_leverage"].value,
                    unit=upstream.facts["fy2025_leverage"].unit,
                    authoritative=False,
                    reference_id=upstream.id,
                ),
                SupportValue(
                    label="Authoritative filing",
                    value=filing.facts["fy2025_leverage"].value,
                    unit=filing.facts["fy2025_leverage"].unit,
                    authoritative=True,
                    reference_id=filing.id,
                ),
                SupportValue(
                    label="Deterministic leverage tool",
                    value=(
                        leverage_tool.output
                        if isinstance(leverage_tool.output, (float, str))
                        else str(leverage_tool.output)
                        if leverage_tool.output is not None
                        else "FAILED"
                    ),
                    unit=leverage_tool.units or "",
                    authoritative=True,
                    reference_id=leverage_tool.id,
                ),
            ),
            failure_rationale=failure.rationale if failure else None,
            permission_denial=(
                PermissionDenial(
                    actor=denial_event.actor.value,
                    capability=str(denial_event.details["capability"]),
                    rationale=str(denial_event.details["reason"]),
                    sequence=denial_event.sequence,
                )
                if denial_event
                else None
            ),
        )

    def decision_view(self) -> DecisionView | None:
        investigation = self.current_investigation()
        if investigation is None:
            return None
        decision = investigation.governance_decisions[-1] if investigation.governance_decisions else None
        recommendation = None
        premises: tuple[str, ...] = ()
        if investigation.active_thesis_id:
            thesis = investigation.theses[investigation.active_thesis_id]
            recommendation_claim = investigation.claims[thesis.recommendation_claim_id]
            recommendation = recommendation_claim.text
            premises = tuple(
                investigation.claims[premise_id].text
                for premise_id in recommendation_claim.premise_claim_ids
                if premise_id in investigation.claims
            )
        return DecisionView(
            machine_verification=(
                "PASSED" if decision and decision.machine_verification_passed else "NOT CLEARED"
            ),
            risk_classification=investigation.risk_classification.value,
            governance_status=investigation.governance_status.value,
            human_review_status=investigation.human_review_status.value,
            lifecycle_status=investigation.lifecycle_status.value,
            recommendation=recommendation,
            supporting_premises=premises,
            decision_recorded=bool(investigation.human_decisions),
        )

    def audit_timeline(self, *, full: bool = False) -> tuple[AuditItem, ...]:
        investigation = self.current_investigation()
        if investigation is None:
            return ()
        priority = {
            EventType.RISK_EVENT_RECEIVED,
            EventType.INVESTIGATION_STARTED,
            EventType.TOOL_REQUESTED,
            EventType.PERMISSION_DENIED,
            EventType.EVIDENCE_ADDED,
            EventType.CLAIM_CREATED,
            EventType.VERIFICATION_FAILED,
            EventType.CLAIM_REVISED,
            EventType.VERIFICATION_PASSED,
            EventType.GOVERNANCE_EVALUATED,
            EventType.HUMAN_REVIEW_REQUIRED,
            EventType.HUMAN_DECISION,
        }
        events = investigation.audit_events if full else [
            event for event in investigation.audit_events if event.event_type in priority
        ]
        return tuple(
            AuditItem(
                sequence=event.sequence,
                actor=event.actor.value,
                event_type=event.event_type.value,
                summary=_audit_summary(event.event_type, event.related_object_id, event.details),
            )
            for event in events
        )

    def _build_provider(self):  # type: ignore[no-untyped-def]
        if self.provider_name == "offline":
            return OfflineReasoningProvider()
        availability = gemini_availability(
            self.environment, default_adc_path=self.default_adc_path
        )
        if not availability.available:
            raise GeminiUnavailableError(availability.reason)
        return configured_gemini_provider(
            deterministic_fallback=self.deterministic_fallback
        )


class CloudDemoApplication(DemoApplication):
    """Same presentation service backed by the worker API and asynchronous Pub/Sub path."""

    def __init__(self, api: WorkerApi, config: CloudConfig) -> None:
        super().__init__(
            provider_name=config.reasoning_provider,
            deterministic_fallback=config.deterministic_fallback,
        )
        self._api = api
        self._cloud_config = config
        current = self._api.get_investigation()
        self._triggered = _cloud_investigation_ready(current)

    def reset(self) -> PortfolioView:
        self._api.reset_demo()
        self._triggered = False
        return self.portfolio_view()

    def trigger(self) -> Investigation:
        existing = self._api.get_investigation()
        if _cloud_investigation_ready(existing):
            self._triggered = True
            assert existing is not None
            return existing
        if existing is None:
            self._api.publish_event()
        deadline = time.monotonic() + self._cloud_config.event_poll_timeout_seconds
        while time.monotonic() < deadline:
            investigation = self._api.get_investigation()
            if _cloud_investigation_ready(investigation):
                self._triggered = True
                assert investigation is not None
                return investigation
            time.sleep(self._cloud_config.event_poll_seconds)
        raise RuntimeError("event published, but investigation was not available before timeout")

    def current_investigation(self) -> Investigation | None:
        investigation = self._api.get_investigation()
        self._triggered = _cloud_investigation_ready(investigation)
        return investigation

    def record_human_decision(
        self,
        *,
        action: HumanAction,
        reviewer: str,
        rationale: str,
    ) -> Investigation:
        reviewer = reviewer.strip()
        rationale = rationale.strip()
        if not reviewer:
            raise DecisionInputError("Reviewer identity is required.")
        if not rationale:
            raise DecisionInputError("Decision rationale is required.")
        return self._api.record_decision(
            action=action, reviewer=reviewer, rationale=rationale
        )


class CloudRunWorkerApi:
    def __init__(self, base_url: str, *, authenticated: bool = True) -> None:
        self._base_url = base_url.rstrip("/")
        self._authenticated = authenticated

    def publish_event(self) -> None:
        response = self._request(
            "POST",
            "/events",
            json={
                "schema_version": "1",
                "event_id": "risk-event-acme-001",
                "scenario_id": "acme-synthetic-v1",
            },
        )
        self._require_success(response)

    def get_investigation(self) -> Investigation | None:
        response = self._request("GET", f"/investigations/{INVESTIGATION_ID}")
        if response.status_code == 404:
            return None
        self._require_success(response)
        return Investigation.model_validate(response.json())

    def record_decision(
        self, *, action: HumanAction, reviewer: str, rationale: str
    ) -> Investigation:
        response = self._request(
            "POST",
            f"/investigations/{INVESTIGATION_ID}/decisions",
            json={"action": action.value, "reviewer": reviewer, "rationale": rationale},
        )
        if response.status_code == 409:
            detail = response.json().get("detail", "decision rejected")
            raise DecisionInputError(str(detail))
        self._require_success(response)
        return Investigation.model_validate(response.json())

    def reset_demo(self) -> None:
        response = self._request("POST", "/demo/reset")
        self._require_success(response)

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            headers: dict[str, str] = {}
            if self._authenticated:
                token = id_token.fetch_id_token(Request(), self._base_url)
                headers["Authorization"] = f"Bearer {token}"
            return httpx.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                timeout=20,
                **kwargs,  # type: ignore[arg-type]
            )
        except (GoogleAuthError, httpx.HTTPError) as error:
            raise RuntimeError("worker API request failed") from error

    @staticmethod
    def _require_success(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            try:
                detail = response.json().get("detail", "worker API request failed")
            except ValueError:
                detail = "worker API request failed"
            raise RuntimeError(str(detail)) from error


def configured_demo_application(config: CloudConfig | None = None) -> DemoApplication:
    selected = config or CloudConfig.from_env()
    if selected.app_env == "cloud":
        if not selected.worker_url:
            raise ValueError("WORKER_URL is required by the cloud Streamlit service")
        return CloudDemoApplication(
            CloudRunWorkerApi(selected.worker_url, authenticated=selected.worker_auth),
            selected,
        )
    return DemoApplication(
        provider_name=selected.reasoning_provider,
        deterministic_fallback=selected.deterministic_fallback,
    )


def _cloud_investigation_ready(investigation: Investigation | None) -> bool:
    return bool(
        investigation
        and (
            investigation.human_decisions
            or investigation.lifecycle_status
            in {LifecycleStatus.AWAITING_HUMAN_REVIEW, LifecycleStatus.COMPLETED}
        )
    )


def _task_status(tasks: Mapping[Role, Task], role: Role) -> str:
    task = tasks.get(role)
    return (
        TaskStatus.COMPLETE.value
        if task is not None and task.status == TaskStatus.COMPLETE
        else "PENDING"
    )


def _claim_summary(claims: Sequence[Claim]) -> str:
    if not claims:
        return "No validated claims entered state"
    return "; ".join(claim.text for claim in claims[:2])


def _claim_history(claim) -> ClaimHistoryItem | None:  # type: ignore[no-untyped-def]
    if claim is None:
        return None
    return ClaimHistoryItem(
        claim_id=claim.id,
        text=claim.text,
        value=claim.value,
        unit=claim.unit,
        status=claim.status.value,
        supersedes_claim_id=claim.supersedes_claim_id,
        evidence_ids=claim.evidence_ids,
        tool_execution_ids=claim.tool_execution_ids,
    )


def _audit_summary(
    event_type: EventType, related_object_id: str | None, details: Mapping[str, object]
) -> str:
    if event_type == EventType.PERMISSION_DENIED:
        return f"Denied {details.get('capability')}: {details.get('reason')}"
    if event_type in {EventType.VERIFICATION_FAILED, EventType.VERIFICATION_PASSED}:
        return f"{related_object_id}: {details.get('rationale')}"
    if event_type == EventType.CLAIM_REVISED:
        return (
            f"{details.get('supersedes_claim_id')} revised from {details.get('previous_value')} "
            f"to {details.get('revised_value')} {details.get('units')}"
        )
    if event_type == EventType.GOVERNANCE_EVALUATED:
        return (
            f"{details.get('status')}; machine_passed="
            f"{details.get('machine_verification_passed')}"
        )
    if event_type == EventType.HUMAN_DECISION:
        return f"{details.get('action')} by {details.get('reviewer')}"
    return related_object_id or event_type.value
