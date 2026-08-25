# Chapter 10 — Firestore and Persistence

## Beyond In-Memory Storage

During local development and unit testing, an in-memory dictionary (`InMemoryStateStore`) is fast, clean, and isolated.

In production Cloud Run deployments, however:
* Cloud Run containers are **stateless and ephemeral**: Instances spin up, handle requests, and terminate on idle.
* An in-memory store would lose all investigations, claims, audit trails, and human decisions the moment an instance scales down to zero.

The solution is [`FirestoreStateStore`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/firestore_store.py), which implements the exact same [`StateStore`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/store.py) interface over Google Cloud Firestore Native.

---

## The Document & Subcollection Hierarchy

In Google Cloud Firestore, state is organized as a canonical root document containing independently queryable subcollections:

```text
/investigations/investigation-acme-001 (Root Document)
    │   • id: "investigation-acme-001"
    │   • lifecycle_status: "AWAITING_HUMAN_REVIEW"
    │   • governance_status: "HUMAN_REVIEW_REQUIRED"
    │   • risk_classification: "RED"
    │   • human_review_status: "REQUIRED"
    │   • configured_model_id: "gemini-3.7-flash"
    │   • updated_at: 2026-08-25T00:27:04Z
    │
    ├── /evidence/
    │       ├── evidence-filing-001 (authoritative=True, leverage=3.8x)
    │       ├── evidence-market-001 (authoritative=True, spread=+90bp)
    │       └── evidence-upstream-001 (authoritative=False, leverage=4.1x)
    │
    ├── /claims/
    │       ├── claim-001 (status=REJECTED, value=4.1)
    │       ├── claim-002 (status=VERIFIED, value=3.8, supersedes="claim-001")
    │       ├── claim-003 (status=VERIFIED, value=90.0)
    │       └── claim-004 (status=VERIFIED, value=-2835000.0)
    │
    ├── /tool_executions/
    │       ├── tool-execution-001 (leverage_ratio: 3.8x)
    │       └── tool-execution-004 (duration_spread_pnl: -$2.835m)
    │
    ├── /verification_findings/
    │       ├── finding-001 (Round 1: claim-001 FAILED)
    │       └── finding-007 (Round 2: claim-002 PASSED)
    │
    ├── /model_calls/
    │       ├── model-call-credit (Gemini 3.7 Flash, latency 32.7s)
    │       └── model-call-investigator (Gemini 3.7 Flash, latency 32.7s)
    │
    └── /audit_events/
            ├── 001 (risk_event_received)
            ├── 015 (permission_denied by credit_agent)
            └── 071 (lifecycle_transitioned to AWAITING_HUMAN_REVIEW)
```

### Why Subcollections?
1. **Atomic Root Reads**: Reading `/investigations/investigation-acme-001` provides high-level portfolio summaries and governance state in a single document read.
2. **Targeted Sub-queries**: Compliance tools can query collection group `/claims/` across all historical investigations where `status == "REJECTED"` or `supersedes_claim_id != null` without loading megabytes of audit events into memory.

---

## Transactional State Modifications

When a human reviewer records an approval or an event lease is claimed, race conditions could corrupt state if two requests land simultaneously.

In [`src/institutional_risk_fleet/firestore_store.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/firestore_store.py#L85-L160):

```python
@firestore.transactional
def _acquire_lease_tx(transaction, doc_ref, delivery_id, ttl_seconds):
    snapshot = doc_ref.get(transaction=transaction)
    now = datetime.now(timezone.utc)
    if snapshot.exists:
        data = snapshot.to_dict() or {}
        if data.get("status") == "completed":
            return LeaseAcquisition(acquired=False, status="completed", investigation_id=data.get("investigation_id"))
        # Check lease expiry...
    transaction.set(doc_ref, {"status": "processing", "delivery_id": delivery_id, ...})
    return LeaseAcquisition(acquired=True, status="processing")
```

Firestore transactions ensure ACID isolation: if another worker attempts to acquire the lease at the same millisecond, one transaction commits and the other is safely rolled back.

---

> [!NOTE]
> ### Real Deployment Lesson: Pinned Firestore `(default)` Compatibility
> In `google-api-core 2.35.0`, a path-template expander URL-encoded database ID `(default)` into `%28default%29`, causing Firestore gRPC calls to fail with `400 Invalid database id`.
>
> In [`src/institutional_risk_fleet/firestore_store.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/firestore_store.py#L75-L85), the store explicitly pins `client._database_string_internal = f"projects/{project}/databases/{database}"` to ensure robust compatibility across SDK updates.

---

## Check Your Understanding

1. **Why is keeping the entire conversation transcript insufficient as persistence for this application?**
   * *Answer*: Unstructured chat transcripts cannot be indexed by financial metric, cannot enforce schema constraints, cannot guarantee ACID transactional leases, and force downstream systems to parse raw text rather than typed domain models.
2. **How does Firestore subcollection structure assist regulatory reporting?**
   * *Answer*: Auditors can execute targeted queries directly against subcollections (e.g. searching all `verification_findings` with `result == FAILED`) without parsing entire document trees.

---

## Code-Reading Exercise

Open [`src/institutional_risk_fleet/firestore_store.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/firestore_store.py#L160-L225) and trace `save(investigation)`:
* Notice how it uses a `WriteBatch` to write the root document and all subcollections (`claims`, `evidence`, `audit_events`) in a single atomic batch commit.

---

## Optional Experiment

Inspect the fake Firestore test suite that validates batch persistence and transactional leases offline:

```bash
uv run pytest tests/test_milestone5_cloud.py -k "firestore"
```

Next: [Chapter 11 — Cloud Run and the Live System →](11_cloud_run_and_the_live_system.md)
