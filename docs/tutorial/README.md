# Institutional Risk Agent Fleet — Interactive Tutorial

Welcome to the architectural and code-level tutorial for the **Institutional Risk Agent Fleet**.

This tutorial is not a generic API reference or high-level pitch. It is a pedagogical walkthrough written from first principles for engineers, researchers, and technical leaders who want to understand how to build **governed, auditable multi-agent systems**.

---

## The Core Problem

When deploying Large Language Models (LLMs) in high-stakes institutional environments (such as portfolio credit risk, compliance, or capital allocation), a fundamental dilemma arises:

```text
Probabilistic Reasoning (LLMs)
  • Flexible hypothesis generation
  • Complex contextual synthesis
  • Cross-modal interpretation
         VS.
Deterministic Authority (Institutional Code)
  • Scoped, non-bypassable permissions
  • Reproducible, verifiable arithmetic
  • Immutable audit provenance
  • Strict legal and regulatory accountability
```

The core design principle of this repository is:

> **Gemini reasons and proposes; deterministic code decides what the institution can trust and what the system is allowed to do.**

---

## Recommended Study Pattern

For the most effective learning experience:

```text
Read the intuition
        ↓
Predict what should happen in the scenario
        ↓
Inspect the referenced repository code
        ↓
Run the minimal local test / command
        ↓
Answer the self-check exercise
```

---

## Study Paths

Choose the path that fits your goals:

### 1. Fast Conceptual Path (Core Governance & AI Boundaries)
Focuses on the central thesis of the architecture:
1. [00 — Project in 10 Minutes](00_project_in_10_minutes.md)
2. [01 — The ACME Risk Event](01_the_acme_risk_event.md)
3. [03 — Permissions and Deterministic Tools](03_permissions_and_deterministic_tools.md)
4. [07 — Why 4.1x Fails (Structured Verification)](07_why_4_1x_fails.md)
5. [08 — Governance and the Human Gate](08_governance_and_the_human_gate.md)
6. [12 — End-to-End Trace & Architectural Takeaways](12_end_to_end_trace.md)

### 2. Full Engineering Path (Code, Types, ADK, and Google Cloud)
Comprehensive dive through every subsystem, data structure, and cloud component:
* [00 — Project in 10 Minutes](00_project_in_10_minutes.md): The three-layer architecture and big picture.
* [01 — The ACME Risk Event](01_the_acme_risk_event.md): The frozen scenario and seeded data conflict.
* [02 — Domain State and Provenance](02_domain_state_and_provenance.md): Pydantic models, immutable claim history, and audit chains.
* [03 — Permissions and Deterministic Tools](03_permissions_and_deterministic_tools.md): `CapabilityGate`, `ToolGateway`, and audited permission denials.
* [04 — Reasoning Providers](04_reasoning_providers.md): Pluggable offline vs. Gemini providers and resilient retry boundaries.
* [05 — Google ADK Agent Workflow](05_google_adk_agent_workflow.md): Multi-agent reasoning topology with Google Agent Development Kit.
* [06 — From Model Output to Trusted State](06_from_model_output_to_trusted_state.md): The untrusted-to-trusted boundary in `ReasoningStateAdapter`.
* [07 — Why 4.1x Fails](07_why_4_1x_fails.md): Deterministic structured verification vs. lexical LLM assertions.
* [08 — Governance and the Human Gate](08_governance_and_the_human_gate.md): Policy clearance vs. human review requirements.
* [09 — Pub/Sub and Idempotency](09_pubsub_and_idempotency.md): Asynchronous event ingestion and transactional idempotency leases.
* [10 — Firestore and Persistence](10_firestore_and_persistence.md): Canonical root snapshots and queryable subcollections.
* [11 — Cloud Run and the Live System](11_cloud_run_and_the_live_system.md): Dual-service single-image deployment with IAM auth.
* [12 — End-to-End Trace](12_end_to_end_trace.md): Step-by-step lifecycle execution of a real risk event.

---

## Prerequisites & Setup

You can follow almost all chapters locally without a Google Cloud account or Gemini API key by running in **offline mode**.

To set up your local environment:

```bash
# Clone and enter directory
cd institutional-risk-agent-fleet

# Install locked dependencies with uv
uv sync --locked

# Run the full test suite
uv run pytest

# Run the interactive CLI demo
uv run python -m institutional_risk_fleet.demo
```

Let's begin with [Chapter 00: Project in 10 Minutes →](00_project_in_10_minutes.md)
