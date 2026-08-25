# Chapter 11 — Cloud Run and the Live System

## The Production Topology

When deploying to Google Cloud, the system is provisioned as two Cloud Run services sharing a single hardened container image:

```mermaid
flowchart TB
    PUB["Pub/Sub Topic<br/><code>risk-events</code>"] -->|OIDC Auth Push| WORKER["Private Cloud Run Worker<br/><code>risk-fleet-worker</code><br/>(FastAPI / Uvicorn)"]
    
    subgraph BACKEND["SECURE BACKEND RUNTIME"]
        WORKER --> WF["DeterministicRiskWorkflow"]
        WF --> ADK["Gemini 3.7 Flash via Google ADK"]
        WF --> FS[("Cloud Firestore")]
        WF --> CL["Cloud Logging"]
    end
    
    UI["Public Cloud Run UI<br/><code>risk-fleet-ui</code><br/>(Streamlit)"] -->|Signed ID Token (run.invoker)| WORKER
    USER["Judge / Risk Officer"] --> UI

    classDef pub fill:#e0f2fe,stroke:#0284c7,color:#0369a1;
    classDef priv fill:#fee2e2,stroke:#ef4444,color:#991b1b;
    classDef store fill:#fef3c7,stroke:#d97706,color:#92400e;
    class UI,USER pub;
    class WORKER,WF,ADK,CL priv;
    class FS store;
```

---

## One Container Image, Two Service Modes

Why build a single Docker image for both worker and UI?
* **Build Reproducibility**: Both services share identical Python package versions, lockfiles, and domain types.
* **Single Deployment Artifact**: Built and pushed once to Artifact Registry (`risk-fleet:m5`).

The runtime behavior is selected via environment variable in [`src/institutional_risk_fleet/cloud_entrypoint.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/cloud_entrypoint.py):

```python
def main() -> None:
    mode = os.getenv("SERVICE_MODE", "worker").strip().lower()
    if mode == "ui":
        # Launch Streamlit frontend:
        os.execvp("streamlit", ["streamlit", "run", "app/streamlit_app.py", "--server.port=8080", ...])
    else:
        # Launch FastAPI worker:
        uvicorn.run("institutional_risk_fleet.cloud_api:app", host="0.0.0.0", port=8080, ...)
```

---

## Security Boundaries & Least-Privilege IAM

Look at how IAM roles separate responsibilities:

| Identity / Service Account | Assigned Roles | Why? |
| :--- | :--- | :--- |
| **`risk-fleet-worker`** (Worker SA) | `roles/datastore.user`<br/>`roles/aiplatform.user`<br/>`roles/logging.logWriter` | Authorized to read/write Firestore, invoke Vertex AI Gemini models, and write Cloud Logs. |
| **`risk-fleet-ui`** (UI SA) | `roles/run.invoker` | **Zero database or AI permissions.** Can only invoke the private worker API via authenticated ID tokens. |
| **`risk-fleet-push`** (Pub/Sub SA) | `roles/run.invoker` | Used by Pub/Sub to mint OIDC tokens targeting `https://risk-fleet-worker-.../pubsub/push`. |

---

## Authenticated ID Token Invocations

When a user in the Streamlit UI triggers a reset or records a human decision, the UI backend requests a signed Google ID token ([`src/institutional_risk_fleet/ui_service.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/ui_service.py#L35-L60)):

```python
class CloudRunWorkerApi:
    def _auth_headers(self) -> dict[str, str]:
        if not self.auth_enabled:
            return {}
        # Mint OIDC token for the worker service audience:
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, self.worker_url)
        return {"Authorization": f"Bearer {token}"}
```

Cloud Run's front-proxy inspects the `Authorization: Bearer <token>` header and verifies that the calling identity has `roles/run.invoker` on `risk-fleet-worker`. Unauthenticated calls are rejected with `HTTP 403 Forbidden` at the Google Cloud edge.

---

## Check Your Understanding

1. **Why is the worker private while the UI is public?**
   * *Answer*: The UI is the public interface for judges and human reviewers. The worker possesses direct write access to Firestore and Vertex AI and must only accept authenticated requests from the UI or verified Pub/Sub push subscriptions.
2. **Does Cloud Run make Credit and Market separate "agents"?**
   * *Answer*: No. Cloud Run simply hosts the container process. Credit and Market are reasoning roles executed within the ADK pipeline inside that process.

---

## Code-Reading Exercise

Open [`src/institutional_risk_fleet/cloud_api.py`](file:///Users/xq/Documents/GitHub/institutional-risk-agent-fleet/src/institutional_risk_fleet/cloud_api.py#L60-L120) and trace:
* `POST /pubsub/push`: Look at how incoming push envelopes are decoded from base64 and passed to `event_handler.handle_risk_event(...)`.
* `POST /api/human-decision`: Trace how human decisions are received and executed.

---

## Optional Experiment

View the complete Cloud Deployment reference guide:

```bash
cat docs/cloud_deployment.md
```

Next: [Chapter 12 — End-to-End Trace →](12_end_to_end_trace.md)
