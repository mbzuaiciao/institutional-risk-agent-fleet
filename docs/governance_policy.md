# Governance policy

## Capabilities

Capabilities are granted to active role contexts in code. A tool call has no `actor`
parameter; its gateway was already bound to a role by orchestration.

- Orchestrator: create tasks, inspect status, and route.
- Credit: issuer financials, credit evidence, and credit tools.
- Market: market history, comparables, and spread tools.
- Evidence: retrieve and register synthetic evidence.
- Investigator: read artifacts, construct a thesis, and use the limited portfolio tools.
- Challenger: read artifacts and create non-authoritative challenges.
- Verifier: read artifacts and create verification findings.
- Human: record a review decision.

The frozen demo deliberately asks the Credit role to use `portfolio_exposure`. The gateway
audits `permission_denied` and raises `PermissionDenied`; the workflow catches the denial
only after it is visible in the audit history.

The Challenger deliberately lacks `CREATE_FINDING`, tool, portfolio, governance, and human-decision
capabilities. Model outputs also cannot provide an `author` field; the canonical adapter assigns it.

## Claim rules

- Material factual claims require evidence IDs.
- Material numeric claims require metric, value, unit, and period.
- Calculated claims require tool-execution IDs.
- Inference and recommendation claims require premise-claim IDs.
- Numeric verification compares structured values and units; it does not use lexical overlap.
- Recommendation claims pass only when their premises are verified.

## Governance and escalation

Machine clearance requires all active claims to pass structured verification, all references
to exist, tool executions to have succeeded, and recommendation premises to be verified.
One deterministic revision is allowed.

Malformed model output, empty output, timeouts, provider errors, and unknown artifact references
cannot enter canonical claim state. Gemini retries are bounded. Without an explicitly configured
fallback, exhausted provider failure escalates the investigation to required human review. With a
fallback, the deterministic path is used and the choice is recorded as `model_fallback_used`.

HIGH severity or exposure of at least $50 million requires human review even after machine
clearance. APPROVE and REJECT are final decisions. REQUEST_MORE_INVESTIGATION returns the
lifecycle to investigation and is not final completion. Reviewer identity and rationale are
required.

Audit events are appended through one API and use contiguous, one-based sequences and stable
event IDs. Earlier claims and verification failures remain present after revision.
