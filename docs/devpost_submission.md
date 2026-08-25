# Devpost submission draft

Replace the bracketed hosted/video placeholders only after verifying their public accessibility.

## Category

Fortified Enterprise Fleet

## Project title

Institutional Risk Agent Fleet

## Tagline

An autonomous Gemini agent fleet for institutional risk investigation, bounded by deterministic
verification and an explicit human decision.

## Inspiration / Problem

Autonomous agents can collect evidence and form recommendations, but institutional deployment needs
more than plausible model output. Agent access must be scoped, calculations reproducible, material
claims traceable and verified, errors retained for audit, and consequential actions escalated. Our
core proposition is simple: autonomous institutional agents should not merely be intelligent; they
should be governable.

## What it does

A synthetic ACME Corp credit event arrives against a $75 million portfolio exposure after spreads
widen from 120bp to 210bp. The event asynchronously starts a multi-agent investigation. The fleet
analyzes credit and market evidence, synthesizes a thesis, challenges its own proposal, and hands
structured claims to deterministic verification and governance. The result is persisted and shown in
a judge-facing interface, with a human remaining the final authority.

The system investigates and recommends; it does not execute trades.

## How it works

Pub/Sub delivers a versioned risk event to a private Cloud Run worker. Google ADK orchestrates Gemini
3.7 Flash roles: Credit and Market run in parallel, followed by Investigator and Challenger. Before
reasoning, deterministic role-bound gateways retrieve registered evidence and execute financial
tools. Strict schemas and a validating adapter prevent invented references from entering canonical
state.

A deterministic Verifier checks values, units, periods, evidence identity, tool lineage, and
premises. The Governance Engine then applies lifecycle and escalation rules. Firestore persists the
investigation, claim versions, decisions, event receipts, and ordered audit trail. A separate Cloud
Run Streamlit service reads and updates state only through the authenticated worker API. Cloud
Logging records structured infrastructure events.

## Agent workflow

```text
Credit + Market
      ↓
 Investigator
      ↓
  Challenger
      ↓
deterministic verification
      ↓
   governance
      ↓
 human review
```

The four reasoning roles propose analysis. Evidence access, tools, permissions, reference
validation, verification, governance, lifecycle, audit sequencing, and human-decision enforcement
remain deterministic.

## Governance differentiator

- Permissions are enforced in code and denied attempts remain visible in the audit trail.
- Financial tools are deterministic and preserve inputs, outputs, units, actor, and provenance.
- Material claims require evidence and tool lineage and pass numeric, unit, period, and identity checks.
- Challenger output is adversarial but non-authoritative; only the Verifier can change claim status.
- Revisions preserve history through explicit supersession instead of overwriting errors.
- Machine verification, risk classification, governance, lifecycle, and human status remain separate.
- Duplicate Pub/Sub deliveries and concurrent human decisions are handled transactionally.

## Demo example

An upstream synthetic source proposes FY2025 leverage of 4.1x. The authoritative synthetic filing
and deterministic leverage tool both establish 3.8x. The Verifier preserves `claim-001` as REJECTED
and creates `claim-002` as VERIFIED with an explicit supersession link. Machine verification passes,
but risk remains RED and governance returns HUMAN_REVIEW_REQUIRED. The Credit Agent's attempted
portfolio access is also blocked by its role-bound capability set and audited.

## Google technologies used

- Gemini 3.7 Flash on Vertex AI
- Google Agent Development Kit (ADK)
- Cloud Run
- Firestore
- Pub/Sub
- Cloud Logging

## Data sources

All portfolio, issuer, market, financial, and source-document data is synthetic and checked into the
repository as the frozen ACME scenario. No live issuer filing, market feed, or customer data is used.

## Challenges we ran into

Real infrastructure exposed boundary cases that local mocks did not: Firestore's default-database
client path behavior, transport metadata in real Pub/Sub push envelopes, and duplicate proposal IDs
carried across live Gemini roles. The hardest design constraint was preserving strict domain
validation without pretending generative output would always be perfect. We isolated compatibility
at adapters, normalized only transport metadata, rejected unsafe references before mutation, and
kept deterministic controls binding.

## Accomplishments

- A live asynchronous Google Cloud deployment with a public UI and private worker
- A real Gemini/ADK multi-agent investigation with bounded, structured role outputs
- Idempotent event processing and transactional human decisions
- Deterministic permissions, financial tools, verification, and governance
- Persisted rejected and corrected claims with explicit lineage
- A visible, enforced human boundary and ordered audit trail
- 66 credential-free passing tests in the final repository gate

## What we learned

Agent reliability is less about adding more agents and more about separating model reasoning from
institutional authority. Strict permissions, stable provenance, deterministic tools, binding
verification, and human escalation made the system more trustworthy than model confidence or agent
count could. Failures also became easier to diagnose once proposed reasoning and authoritative state
were distinct artifacts.

## What's next

Future research can broaden scenarios and asset classes, strengthen enterprise identity and evidence
independence, and study uncertainty across conflicting sources. Live financial data should be added
only after those governance controls are hardened beyond the hackathon setting.

## Links

- Hosted project: **[ADD VERIFIED PUBLIC CLOUD RUN UI URL]**
- Public demo video: **[ADD PUBLIC YOUTUBE OR VIMEO URL]**
- Repository: https://github.com/mbzuaiciao/institutional-risk-agent-fleet
- Architecture: `docs/architecture.md`
- Reproducible setup: `README.md` and `docs/cloud_deployment.md`
