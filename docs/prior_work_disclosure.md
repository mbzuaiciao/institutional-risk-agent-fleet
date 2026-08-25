# Prior-work disclosure

This repository is a new hackathon implementation. No wholesale source files were copied from the
reference repositories, and neither reference repository was modified.

The design was informed conceptually by:

- `institutional-investment-agents`: typed research state, stable evidence/claim/tool IDs,
  support-pointer rules, deterministic financial tools, ordered audit events, and offline acceptance
  testing;
- `k2-risk-agent-lab`: code-enforced capabilities, numeric and unit-aware verification, visible
  permission failures, and abstention/escalation concepts.

The leverage, spread-move, portfolio-exposure, and first-order duration-based spread-P&L formulas
are standard financial arithmetic and were implemented fresh. The schemas, fixture, workflow,
permissions, gateways, provider adapter, versioned prompts, Challenger, verification, governance,
audit logic, cloud adapters, UI, tests, and documentation were written for this repository. Google
ADK integration uses the public Python SDK.
