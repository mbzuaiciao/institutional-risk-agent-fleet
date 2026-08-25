# Chapter 01 — The ACME Risk Event

## Why Does a Frozen Scenario Exist?

In autonomous agent benchmarks, systems are often evaluated against random internet queries or nondeterministic tasks. In financial enterprise systems, evaluating governance requires **reproducible, deterministic ground truth**.

The repository provides a frozen synthetic scenario: `data/synthetic/acme_scenario.json`.

Every test, local run, and live cloud deployment uses this exact scenario to prove that the governance boundary behaves deterministically under stress.

---

## Anatomy of the Scenario Data

Let's inspect the data fields inside [`data/synthetic/acme_scenario.json`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/data/synthetic/acme_scenario.json):

```json
{
  "scenario_id": "scenario-acme-credit-001",
  "version": "1.0.0",
  "event": {
    "id": "risk-event-acme-001",
    "issuer_id": "ACME",
    "issuer_name": "Acme Corp",
    "portfolio_exposure_usd": 75000000.0,
    "previous_spread_bps": 120.0,
    "current_spread_bps": 210.0,
    "spread_move_bps": 90.0,
    "severity": "HIGH",
    "occurred_at": "2026-01-15T14:30:00Z"
  },
  "financials": {
    "issuer_id": "ACME",
    "period": "FY2025",
    "debt_usd_millions": 380.0,
    "ebitda_usd_millions": 100.0,
    "cash_usd_millions": 45.0
  },
  "positions": [
    {
      "position_id": "pos-acme-2029",
      "issuer_name": "Acme Corp",
      "market_value_usd": 40000000.0,
      "spread_duration": 4.1
    },
    {
      "position_id": "pos-acme-2031",
      "issuer_name": "Acme Corp",
      "market_value_usd": 35000000.0,
      "spread_duration": 4.3
    }
  ]
}
```

---

## Manual Arithmetic: Verify the Financials

Let's do the exact math an institutional analyst would perform:

### 1. Spread Move
$$\Delta \text{Spread} = 210.0\text{ bps} - 120.0\text{ bps} = +90.0\text{ bps}$$

In bond markets, 100 basis points equals 1.00% of yield spread. A +90 bps widening in a single session is a major shock.

### 2. Total Exposure
$$\text{Exposure} = \$40,000,000 + \$35,000,000 = \$75,000,000\text{ USD}$$

### 3. Duration-Weighted Spread P&L
The aggregate portfolio spread duration is:
$$\text{Weighted Duration} = \frac{40 \times 4.1 + 35 \times 4.3}{75} = \frac{164 + 150.5}{75} = 4.1933\text{ years}$$

First-order price impact formula:
$$\Delta P \approx - \text{Spread Duration} \times \Delta \text{Spread (decimal)} \times \text{Exposure}$$
$$\Delta P \approx - 4.2 \times 0.0090 \times \$75,000,000 = -\$2,835,000\text{ USD}$$

### 4. Authoritative Gross Leverage Ratio
$$\text{Gross Leverage} = \frac{\text{Total Debt}}{\text{EBITDA}} = \frac{\$380\text{M}}{\$100\text{M}} = 3.80\text{x}$$

---

## The Seeded Upstream-Data Fault

Notice the three pieces of synthetic evidence registered in [`data/synthetic/acme_scenario.json`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/data/synthetic/acme_scenario.json#L40-L75):

1. **`evidence-filing-001`** (`source_type="issuer_filing"`, `authoritative=True`):
   * Audited 10-K filing stating FY2025 Debt = \$380m, EBITDA = \$100m, Gross Leverage = **3.8x**.
2. **`evidence-market-001`** (`source_type="market_snapshot"`, `authoritative=True`):
   * Secondary market trading records confirming the spread move from 120 bps to 210 bps (+90 bps).
3. **`evidence-upstream-001`** (`source_type="upstream_enrichment"`, `authoritative=False`):
   * Automated third-party news/data-feed claiming Acme's FY2025 Gross Leverage is **4.1x**.

> [!IMPORTANT]
> **This is a seeded upstream data conflict, not a model hallucination.**
> In enterprise data engineering, automated feeds often contain stale, unadjusted, or erroneous data. If an AI agent blindly trusts the unauthoritative `4.1x` upstream enrichment, the governance layer must catch the contradiction and reject the claim.

---

## How Code Loads and Freezes the Scenario

Look at [`src/institutional_risk_fleet/scenario.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/scenario.py#L30-L55):

```python
class FrozenScenario(FrozenModel):
    scenario_id: str
    version: str
    event: RiskEvent
    financials: IssuerFinancials
    positions: tuple[PortfolioPosition, ...]
    evidence: tuple[Evidence, ...]


def load_default_scenario() -> FrozenScenario:
    path = Path(__file__).resolve().parent.parent.parent / "data/synthetic/acme_scenario.json"
    return load_scenario_from_file(path)
```

Notice that `FrozenScenario` uses immutable tuple structures and frozen Pydantic models. Once loaded, no component or agent can mutate the ground-truth scenario in memory.

---

## Check Your Understanding

1. **Why is `evidence-filing-001` marked `authoritative=True` while `evidence-upstream-001` is marked `authoritative=False`?**
   * *Answer*: Audited regulatory filings (10-K) take legal precedence over third-party data aggregators and automated news enrichment pipelines.
2. **What is the difference between a model hallucination and an upstream data fault?**
   * *Answer*: A hallucination is fabricated by the LLM without external prompt support. An upstream data fault is corrupted or erroneous information present in external data feeds. Robust systems must defend against both.

---

## Code-Reading Exercise

Open [`src/institutional_risk_fleet/domain.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/domain.py#L128-L175) and inspect:
1. `RiskEvent`: Check how `spread_move_bps` is validated against `current_spread_bps - previous_spread_bps`.
2. `Evidence`: Check the `authoritative: bool` field and the `NormalizedFact` dictionary.

---

## Optional Experiment

1. Copy `data/synthetic/acme_scenario.json` to a temporary file.
2. Change `"current_spread_bps"` from `210.0` to `150.0` (a +30 bps move instead of +90 bps).
3. Predict how the severity and duration P&L change:
   $$\Delta P \approx -4.2 \times 0.0030 \times \$75\text{M} = -\$945,000\text{ USD}$$

Next: [Chapter 02 — Domain State and Provenance →](02_domain_state_and_provenance.md)
