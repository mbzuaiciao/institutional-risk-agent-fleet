"""Concise offline demonstration entry point."""

from __future__ import annotations

import argparse
import os

from institutional_risk_fleet.adk_provider import configured_gemini_provider
from institutional_risk_fleet.domain import FindingResult, HumanAction
from institutional_risk_fleet.reasoning import OfflineReasoningProvider
from institutional_risk_fleet.workflow import DeterministicRiskWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the synthetic Acme governance demo.")
    parser.add_argument(
        "--provider",
        choices=("offline", "gemini"),
        default=os.getenv("RISK_FLEET_PROVIDER", "offline"),
    )
    parser.add_argument(
        "--deterministic-fallback",
        action="store_true",
        help="Explicitly permit a labeled offline fallback after bounded Gemini failures.",
    )
    parser.add_argument(
        "--decision",
        choices=("approve", "reject", "more"),
        help="Optionally record a human decision after the machine workflow.",
    )
    parser.add_argument("--reviewer", default="Demo Risk Officer")
    parser.add_argument(
        "--rationale",
        default="Reviewed the synthetic evidence, revision, and governance trace.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    provider = (
        OfflineReasoningProvider()
        if args.provider == "offline"
        else configured_gemini_provider(
            deterministic_fallback=args.deterministic_fallback
        )
    )
    workflow = DeterministicRiskWorkflow(reasoning_provider=provider)
    investigation = workflow.run()
    leverage_failure = next((
        finding
        for finding in investigation.verification_findings
        if finding.target_claim_id == "claim-001" and finding.result == FindingResult.FAILED
    ), None)
    leverage_pass = next((
        finding
        for finding in investigation.verification_findings
        if finding.result == FindingResult.PASSED
        and investigation.claims[finding.target_claim_id].metric == "fy2025_leverage"
    ), None)
    denied = next(
        event for event in investigation.audit_events if event.event_type.value == "permission_denied"
    )
    print(f"INSTITUTIONAL RISK AGENT FLEET — {args.provider.upper()} SYNTHETIC DEMO")
    print(
        f"Provider: {investigation.reasoning_provider}; "
        f"model={investigation.configured_model_id or 'none'}; "
        f"fallback={any(call.fallback_used for call in investigation.model_calls)}"
    )
    if investigation.model_calls:
        print(
            "ADK model roles recorded: "
            + ", ".join(dict.fromkeys(call.role.value for call in investigation.model_calls))
        )
    print("1. ACME risk event received: spread +90bp, exposure $75m, severity HIGH.")
    print("2. Investigation created; evidence, Credit, and Market tasks completed.")
    print(
        "3. Credit Agent portfolio request: DENIED "
        f"({denied.details['capability']}); audit event {denied.id}."
    )
    if leverage_failure and leverage_pass:
        print("4. Investigator adopted upstream claim-001: FY2025 leverage = 4.1x.")
        print(
            "5. Verification FAILED: "
            f"observed {leverage_failure.observed_value}x, expected {leverage_failure.expected_value}x."
        )
        print("6. claim-001 retained as REJECTED; claim-002 created with supersedes_claim_id=claim-001.")
        print(
            "7. Re-verification PASSED: "
            f"claim-002 = {leverage_pass.observed_value}x with filing and deterministic-tool lineage."
        )
    else:
        print(
            f"4. Reasoning completed with {len(investigation.challenges)} Challenger output(s); "
            "deterministic verification remained authoritative."
        )
    final = investigation.governance_decisions[-1] if investigation.governance_decisions else None
    machine_status = "PASSED" if final and final.machine_verification_passed else "NOT CLEARED"
    print(f"8. Machine verification: {machine_status}. Risk classification: RED.")
    print(
        f"9. Governance result: {investigation.governance_status.value}. "
        "No automatic approval occurred."
    )
    if args.decision:
        action = {
            "approve": HumanAction.APPROVE,
            "reject": HumanAction.REJECT,
            "more": HumanAction.REQUEST_MORE_INVESTIGATION,
        }[args.decision]
        investigation = workflow.record_human_decision(
            investigation.id,
            action=action,
            reviewer=args.reviewer,
            rationale=args.rationale,
        )
        print(
            f"10. Human decision recorded: {action.value}; "
            f"lifecycle={investigation.lifecycle_status.value}."
        )


if __name__ == "__main__":
    main()
