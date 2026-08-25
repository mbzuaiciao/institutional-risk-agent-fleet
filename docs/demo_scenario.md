# Frozen demo scenario

All values and sources described here are synthetic.

## Trigger

- Issuer: Acme Corp
- Portfolio exposure: $75 million
- Previous spread: 120bp
- Current spread: 210bp
- Spread move: +90bp
- Severity: HIGH

The checked-in fixture is `data/synthetic/acme_scenario.json`. Acme's synthetic FY2025
financial inputs are debt of $380 million and EBITDA of $100 million, producing deterministic
gross leverage of 3.8x. Spread duration is 4.2, so the +90bp event produces an approximate
first-order spread P&L of -$2.835 million on the $75 million position.

## Seeded upstream fault

An upstream enrichment record reports FY2025 leverage of 4.1x. The Investigator initially
adopts that material numeric claim. The authoritative synthetic filing reports 3.8x, and the
credit tool independently computes 3.8x.

The first verification round rejects `claim-001` at 4.1x. The revision path creates
`claim-002` at 3.8x with both filing and tool lineage and with
`supersedes_claim_id="claim-001"`. The rejected claim is retained.

After re-verification, all active material claims pass. Governance nevertheless assigns RED
and HUMAN_REVIEW_REQUIRED because the event is HIGH severity and the $75 million exposure
exceeds the configured $50 million human-review threshold.
