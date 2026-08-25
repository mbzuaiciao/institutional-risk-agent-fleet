"""Deterministic control plane with pluggable offline or Gemini reasoning."""

from __future__ import annotations

from contextlib import suppress

from pydantic import ValidationError

from institutional_risk_fleet.audit import AuditLog, assert_coherent_audit
from institutional_risk_fleet.domain import (
    Claim,
    ClaimType,
    EventType,
    GovernanceStatus,
    HumanAction,
    HumanDecision,
    HumanReviewStatus,
    Investigation,
    LifecycleStatus,
    Role,
    Task,
    TaskStatus,
    Thesis,
)
from institutional_risk_fleet.governance import GovernanceEngine
from institutional_risk_fleet.permissions import (
    Capability,
    CapabilityGate,
    PermissionDenied,
    RoleContext,
)
from institutional_risk_fleet.reasoning import (
    OfflineReasoningProvider,
    ReasoningContext,
    ReasoningOutputError,
    ReasoningProvider,
    ReasoningProviderError,
)
from institutional_risk_fleet.reasoning_adapter import ReasoningStateAdapter
from institutional_risk_fleet.scenario import FrozenScenario, load_default_scenario
from institutional_risk_fleet.store import InMemoryStateStore, StateStore
from institutional_risk_fleet.tools import ToolGateway
from institutional_risk_fleet.transitions import transition_lifecycle
from institutional_risk_fleet.verification import StructuredVerifier


class DeterministicRiskWorkflow:
    """Authoritative deterministic control plane with pluggable reasoning."""

    def __init__(
        self,
        store: StateStore | None = None,
        *,
        reasoning_provider: ReasoningProvider | None = None,
    ) -> None:
        self.store = store or InMemoryStateStore()
        self.reasoning_provider = reasoning_provider or OfflineReasoningProvider()
        self.audit = AuditLog()
        self.gate = CapabilityGate(self.audit)
        self.governance = GovernanceEngine(self.audit)

    def run(self, scenario: FrozenScenario | None = None) -> Investigation:
        selected = scenario or load_default_scenario()
        investigation = Investigation(
            id="investigation-acme-001",
            event=selected.event,
            reasoning_provider=self.reasoning_provider.name,
            configured_model_id=self.reasoning_provider.model_id,
        )
        self.store.create(investigation)
        self.audit.append(
            investigation,
            EventType.RISK_EVENT_RECEIVED,
            Role.ORCHESTRATOR,
            selected.event.id,
            issuer=selected.event.issuer_name,
            spread_move_bps=selected.event.spread_move_bps,
            severity=selected.event.severity.value,
        )
        self.audit.append(
            investigation,
            EventType.INVESTIGATION_STARTED,
            Role.ORCHESTRATOR,
            investigation.id,
            scenario_id=selected.scenario_id,
            scenario_version=selected.version,
        )
        transition_lifecycle(
            investigation,
            LifecycleStatus.INVESTIGATING,
            actor=Role.ORCHESTRATOR,
            audit=self.audit,
        )
        self._create_tasks(investigation)
        self._gather_evidence(investigation, selected)
        leverage_execution = self._run_credit_work(investigation, selected)
        spread_execution = self._run_market_work(investigation, selected)
        _exposure_execution, pnl_execution = self._run_portfolio_tools(investigation, selected)
        context = ReasoningContext(
            investigation_id=investigation.id,
            scenario_id=selected.scenario_id,
            scenario_version=selected.version,
            event=selected.event.model_dump(mode="json"),
            evidence=tuple(item.model_dump(mode="json") for item in investigation.evidence.values()),
            tool_results=tuple(
                item.model_dump(mode="json") for item in investigation.tool_executions.values()
            ),
        )

        def observe_model(
            event_type: EventType,
            role: Role,
            request_id: str | None,
            details: dict[str, object],
        ) -> None:
            self.audit.append(
                investigation,
                event_type,
                role,
                request_id,
                **details,
            )

        try:
            outcome = self.reasoning_provider.run(context, observe_model)
        except ReasoningProviderError as error:
            records = getattr(error, "records", ())
            investigation.model_calls.extend(records)
            if not any(
                event.event_type == EventType.MODEL_PROVIDER_FAILED
                for event in investigation.audit_events
            ):
                self.audit.append(
                    investigation,
                    EventType.MODEL_PROVIDER_FAILED,
                    Role.ORCHESTRATOR,
                    None,
                    provider=self.reasoning_provider.name,
                    error_type=type(error).__name__,
                )
            return self._escalate_provider_failure(
                investigation, "model_provider_failed_without_fallback"
            )
        investigation.reasoning_provider = outcome.provider
        investigation.configured_model_id = outcome.model_id
        investigation.model_calls.extend(outcome.model_calls)
        try:
            ReasoningStateAdapter(self.gate, self.audit).apply(investigation, outcome)
        except (ReasoningOutputError, ValidationError) as error:
            self.audit.append(
                investigation,
                EventType.MODEL_OUTPUT_VALIDATION_FAILED,
                Role.ORCHESTRATOR,
                None,
                error_type=type(error).__name__,
                stage="canonical_reference_validation",
            )
            return self._escalate_provider_failure(
                investigation, "model_output_validation_failed"
            )
        self._complete_task(investigation, "task-investigator-001")
        self._complete_task(investigation, "task-challenger-001")

        transition_lifecycle(
            investigation,
            LifecycleStatus.VERIFYING,
            actor=Role.ORCHESTRATOR,
            audit=self.audit,
        )
        verifier = StructuredVerifier(
            RoleContext(Role.VERIFIER), self.gate, self.audit
        )
        round_one = verifier.verify_round(investigation, 1)
        first_decision = self.governance.evaluate(investigation, 1, round_one)
        final_decision = first_decision
        if first_decision.status == GovernanceStatus.REVISION_REQUIRED:
            transition_lifecycle(
                investigation,
                LifecycleStatus.REVISING,
                actor=Role.INVESTIGATOR,
                audit=self.audit,
            )
            self._revise_thesis(
                investigation, leverage_execution.id, spread_execution.id, pnl_execution.id
            )
            investigation.revision_count += 1
            transition_lifecycle(
                investigation,
                LifecycleStatus.VERIFYING,
                actor=Role.ORCHESTRATOR,
                audit=self.audit,
            )
            round_two = verifier.verify_round(investigation, 2)
            final_decision = self.governance.evaluate(investigation, 2, round_two)
        if final_decision.status == GovernanceStatus.HUMAN_REVIEW_REQUIRED:
            transition_lifecycle(
                investigation,
                LifecycleStatus.AWAITING_HUMAN_REVIEW,
                actor=Role.ORCHESTRATOR,
                audit=self.audit,
            )
        elif final_decision.status == GovernanceStatus.READY:
            self.complete_investigation(investigation)
        else:
            raise RuntimeError(f"unexpected final governance status: {final_decision.status}")
        self._complete_task(investigation, "task-verification-001")
        assert_coherent_audit(investigation)
        self.store.save(investigation)
        return investigation.model_copy(deep=True)

    def record_human_decision(
        self,
        investigation_id: str,
        *,
        action: HumanAction,
        reviewer: str,
        rationale: str,
    ) -> Investigation:
        rejected: list[str] = []

        def apply(investigation: Investigation) -> Investigation:
            context = RoleContext(Role.HUMAN)
            self.gate.require(context, Capability.RECORD_HUMAN_DECISION, investigation)
            if investigation.lifecycle_status != LifecycleStatus.AWAITING_HUMAN_REVIEW:
                message = "investigation is not awaiting human review"
                self.audit.append(
                    investigation,
                    EventType.HUMAN_DECISION_REJECTED,
                    Role.HUMAN,
                    None,
                    action=action.value,
                    reviewer=reviewer.strip(),
                    reason=message,
                )
                rejected.append(message)
                return investigation
            decision = HumanDecision(
                id=f"human-decision-{len(investigation.human_decisions) + 1:03d}",
                action=action,
                reviewer=reviewer.strip(),
                rationale=rationale.strip(),
            )
            investigation.human_decisions.append(decision)
            self.audit.append(
                investigation,
                EventType.HUMAN_DECISION,
                Role.HUMAN,
                decision.id,
                action=action.value,
                reviewer=decision.reviewer,
                rationale=decision.rationale,
            )
            if action == HumanAction.REQUEST_MORE_INVESTIGATION:
                investigation.human_review_status = HumanReviewStatus.MORE_INVESTIGATION
                investigation.governance_status = GovernanceStatus.PENDING
                transition_lifecycle(
                    investigation,
                    LifecycleStatus.INVESTIGATING,
                    actor=Role.HUMAN,
                    audit=self.audit,
                )
            else:
                investigation.human_review_status = (
                    HumanReviewStatus.APPROVED
                    if action == HumanAction.APPROVE
                    else HumanReviewStatus.REJECTED
                )
                self.complete_investigation(investigation)
            assert_coherent_audit(investigation)
            return investigation

        result = self.store.update_atomically(investigation_id, apply)
        if rejected:
            raise ValueError(rejected[0])
        return result

    def complete_investigation(self, investigation: Investigation) -> None:
        if investigation.human_review_status == HumanReviewStatus.REQUIRED:
            if not investigation.human_decisions:
                raise ValueError("human-required investigation cannot complete without a decision")
            if investigation.human_decisions[-1].action == HumanAction.REQUEST_MORE_INVESTIGATION:
                raise ValueError("request-more-investigation is not a final decision")
        transition_lifecycle(
            investigation,
            LifecycleStatus.COMPLETED,
            actor=Role.HUMAN
            if investigation.human_decisions
            else Role.ORCHESTRATOR,
            audit=self.audit,
        )
        self.audit.append(
            investigation,
            EventType.INVESTIGATION_COMPLETED,
            Role.HUMAN if investigation.human_decisions else Role.ORCHESTRATOR,
            investigation.id,
            human_review_status=investigation.human_review_status.value,
        )

    def _create_tasks(self, investigation: Investigation) -> None:
        context = RoleContext(Role.ORCHESTRATOR)
        definitions = (
            ("task-evidence-001", Role.EVIDENCE, "Retrieve and register synthetic evidence."),
            ("task-credit-001", Role.CREDIT, "Assess Acme FY2025 credit metrics."),
            ("task-market-001", Role.MARKET, "Assess the Acme spread shock and comparables."),
            ("task-investigator-001", Role.INVESTIGATOR, "Construct and revise the risk thesis."),
            ("task-challenger-001", Role.CHALLENGER, "Challenge the typed reasoning output."),
            ("task-verification-001", Role.VERIFIER, "Adversarially verify material claims."),
        )
        for task_id, role, objective in definitions:
            self.gate.require(context, Capability.CREATE_TASK, investigation)
            task = Task(id=task_id, role=role, objective=objective)
            investigation.tasks[task.id] = task
            self.audit.append(
                investigation,
                EventType.TASK_CREATED,
                Role.ORCHESTRATOR,
                task.id,
                assigned_role=role.value,
                objective=objective,
            )

    def _gather_evidence(
        self, investigation: Investigation, scenario: FrozenScenario
    ) -> None:
        context = RoleContext(Role.EVIDENCE)
        self.gate.require(context, Capability.RETRIEVE_EVIDENCE, investigation)
        for evidence in scenario.evidence:
            self.gate.require(context, Capability.REGISTER_EVIDENCE, investigation)
            investigation.evidence[evidence.id] = evidence
            self.audit.append(
                investigation,
                EventType.EVIDENCE_ADDED,
                Role.EVIDENCE,
                evidence.id,
                source_type=evidence.source_type,
                locator=evidence.locator,
                authoritative=evidence.authoritative,
            )
        self._complete_task(investigation, "task-evidence-001")

    def _run_credit_work(self, investigation: Investigation, scenario: FrozenScenario):
        context = RoleContext(Role.CREDIT)
        self.gate.require(context, Capability.READ_ISSUER_FINANCIALS, investigation)
        gateway = ToolGateway(context, self.gate, self.audit)
        with suppress(PermissionDenied):
            gateway.execute(
                investigation,
                "portfolio_exposure",
                {
                    "position_market_values_usd": [
                        position.market_value_usd for position in scenario.positions
                    ]
                },
            )
        execution = gateway.execute(
            investigation,
            "leverage_ratio",
            {
                "debt_usd_millions": scenario.financials.debt_usd_millions,
                "ebitda_usd_millions": scenario.financials.ebitda_usd_millions,
            },
        )
        if not execution.successful:
            raise RuntimeError("frozen leverage calculation failed")
        self._complete_task(investigation, "task-credit-001")
        return execution

    def _run_market_work(self, investigation: Investigation, scenario: FrozenScenario):
        context = RoleContext(Role.MARKET)
        self.gate.require(context, Capability.READ_MARKET_HISTORY, investigation)
        self.gate.require(context, Capability.READ_COMPARABLES, investigation)
        execution = ToolGateway(context, self.gate, self.audit).execute(
            investigation,
            "spread_move",
            {
                "previous_spread_bps": scenario.event.previous_spread_bps,
                "current_spread_bps": scenario.event.current_spread_bps,
            },
        )
        if not execution.successful:
            raise RuntimeError("frozen spread calculation failed")
        self._complete_task(investigation, "task-market-001")
        return execution

    def _run_portfolio_tools(
        self, investigation: Investigation, scenario: FrozenScenario
    ):
        context = RoleContext(Role.INVESTIGATOR)
        gateway = ToolGateway(context, self.gate, self.audit)
        acme_position = next(
            position for position in scenario.positions if position.issuer_name == "Acme Corp"
        )
        exposure = gateway.execute(
            investigation,
            "portfolio_exposure",
            {"position_market_values_usd": [acme_position.market_value_usd]},
        )
        pnl = gateway.execute(
            investigation,
            "duration_spread_pnl",
            {
                "market_value_usd": acme_position.market_value_usd,
                "spread_duration": acme_position.spread_duration,
                "spread_move_bps": scenario.event.spread_move_bps,
            },
        )
        if not exposure.successful or not pnl.successful:
            raise RuntimeError("frozen portfolio calculations failed")
        return exposure, pnl

    def _construct_initial_thesis(
        self,
        investigation: Investigation,
        leverage_execution_id: str,
        spread_execution_id: str,
        exposure_execution_id: str,
        pnl_execution_id: str,
    ) -> None:
        context = RoleContext(Role.INVESTIGATOR)
        self.gate.require(context, Capability.READ_ARTIFACTS, investigation)
        self.gate.require(context, Capability.CONSTRUCT_THESIS, investigation)
        claims = (
            Claim(
                id="claim-001",
                author=Role.INVESTIGATOR,
                claim_type=ClaimType.FACTUAL,
                text="Acme FY2025 gross leverage is 4.1x.",
                metric="fy2025_leverage",
                value=4.1,
                unit="x",
                period="FY2025",
                evidence_ids=("evidence-upstream-001",),
                confidence=0.72,
            ),
            Claim(
                id="claim-003",
                author=Role.MARKET,
                claim_type=ClaimType.CALCULATED,
                text="Acme spread widened by 90bp.",
                metric="spread_move",
                value=90.0,
                unit="bps",
                period="2026-01-15",
                evidence_ids=("evidence-market-001",),
                tool_execution_ids=(spread_execution_id,),
                confidence=1.0,
            ),
            Claim(
                id="claim-004",
                author=Role.INVESTIGATOR,
                claim_type=ClaimType.CALCULATED,
                text="The +90bp shock implies approximately -$2.835m of first-order spread P&L.",
                metric="spread_pnl",
                value=-2_835_000.0,
                unit="USD",
                period="risk-event-acme-001",
                tool_execution_ids=(pnl_execution_id,),
                confidence=1.0,
            ),
            Claim(
                id="claim-005",
                author=Role.INVESTIGATOR,
                claim_type=ClaimType.RECOMMENDATION,
                text="Escalate Acme for human risk review; do not execute trades.",
                premise_claim_ids=("claim-001", "claim-003", "claim-004"),
                confidence=0.78,
            ),
        )
        for claim in claims:
            self._add_claim(investigation, claim)
        thesis = Thesis(
            id="thesis-001",
            primary_hypothesis="The spread widening reflects issuer-specific credit deterioration.",
            alternative_hypotheses=(
                "The move is partly a broad sector repricing.",
                "Liquidity pressure amplified the observed spread move.",
            ),
            recommendation_claim_id="claim-005",
            claim_ids=tuple(claim.id for claim in claims),
            confidence=0.72,
            uncertainties=("Upstream and filing leverage values conflict.",),
        )
        investigation.theses[thesis.id] = thesis
        investigation.active_thesis_id = thesis.id
        self._complete_task(investigation, "task-investigator-001")

    def _revise_thesis(
        self,
        investigation: Investigation,
        leverage_execution_id: str,
        spread_execution_id: str,
        pnl_execution_id: str,
    ) -> None:
        corrected = Claim(
            id="claim-002",
            author=Role.INVESTIGATOR,
            claim_type=ClaimType.CALCULATED,
            text="Acme FY2025 gross leverage is 3.8x.",
            metric="fy2025_leverage",
            value=3.8,
            unit="x",
            period="FY2025",
            evidence_ids=("evidence-filing-001",),
            tool_execution_ids=(leverage_execution_id,),
            confidence=1.0,
            supersedes_claim_id="claim-001",
        )
        recommendation = Claim(
            id="claim-006",
            author=Role.INVESTIGATOR,
            claim_type=ClaimType.RECOMMENDATION,
            text="Escalate Acme for human risk review; do not execute trades.",
            premise_claim_ids=("claim-002", "claim-003", "claim-004"),
            confidence=0.82,
            supersedes_claim_id="claim-005",
        )
        self._add_claim(investigation, corrected)
        self.audit.append(
            investigation,
            EventType.CLAIM_REVISED,
            Role.INVESTIGATOR,
            corrected.id,
            supersedes_claim_id="claim-001",
            previous_value=4.1,
            revised_value=3.8,
            units="x",
        )
        self._add_claim(investigation, recommendation)
        thesis = Thesis(
            id="thesis-002",
            primary_hypothesis="The spread widening is material despite corrected leverage of 3.8x.",
            alternative_hypotheses=(
                "The move is partly a broad sector repricing.",
                "Liquidity pressure amplified the observed spread move.",
            ),
            recommendation_claim_id="claim-006",
            claim_ids=("claim-002", "claim-003", "claim-004", "claim-006"),
            confidence=0.82,
            uncertainties=("The split between issuer-specific and sector drivers remains uncertain.",),
            supersedes_thesis_id="thesis-001",
        )
        investigation.theses[thesis.id] = thesis
        investigation.active_thesis_id = thesis.id

    def _add_claim(self, investigation: Investigation, claim: Claim) -> None:
        if claim.id in investigation.claims:
            raise ValueError(f"duplicate claim ID: {claim.id}")
        if claim.supersedes_claim_id and claim.supersedes_claim_id not in investigation.claims:
            raise ValueError("superseded claim must already exist")
        investigation.claims[claim.id] = claim
        self.audit.append(
            investigation,
            EventType.CLAIM_CREATED,
            claim.author,
            claim.id,
            claim_type=claim.claim_type.value,
            evidence_ids=list(claim.evidence_ids),
            tool_execution_ids=list(claim.tool_execution_ids),
            premise_claim_ids=list(claim.premise_claim_ids),
            supersedes_claim_id=claim.supersedes_claim_id,
        )

    def _complete_task(self, investigation: Investigation, task_id: str) -> None:
        task = investigation.tasks[task_id]
        if task.status == TaskStatus.COMPLETE:
            return
        investigation.tasks[task_id] = task.model_copy(update={"status": TaskStatus.COMPLETE})
        self.audit.append(
            investigation,
            EventType.TASK_COMPLETED,
            task.role,
            task.id,
        )

    def _escalate_provider_failure(
        self, investigation: Investigation, reason: str
    ) -> Investigation:
        self.governance.escalate_operational_failure(
            investigation, reason=reason
        )
        transition_lifecycle(
            investigation,
            LifecycleStatus.AWAITING_HUMAN_REVIEW,
            actor=Role.ORCHESTRATOR,
            audit=self.audit,
        )
        assert_coherent_audit(investigation)
        self.store.save(investigation)
        return investigation.model_copy(deep=True)
