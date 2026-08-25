# Google Cloud deployment

The live-validated deployment uses one image and two Cloud Run services. The worker/API is private. Authenticated
Pub/Sub push and the Streamlit service account are its only invokers. The Streamlit service is the
judge-facing surface and never writes Firestore or runs the workflow directly.

These commands are intentionally explicit and do not require Terraform. Run them from the repository
root with a Google Cloud project where billing is enabled. Choose a Firestore-compatible region.

## 1. Select names and enable APIs

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export REPOSITORY="risk-fleet"
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/risk-fleet:m5"
export WORKER_SERVICE="risk-fleet-worker"
export UI_SERVICE="risk-fleet-ui"
export TOPIC="risk-events"
export SUBSCRIPTION="risk-events-worker-push"
export WORKER_SA="risk-fleet-worker@$PROJECT_ID.iam.gserviceaccount.com"
export UI_SA="risk-fleet-ui@$PROJECT_ID.iam.gserviceaccount.com"
export PUSH_SA="risk-fleet-push@$PROJECT_ID.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  logging.googleapis.com
```

Create the Firestore Native database only if the project does not already have `(default)`:

```bash
gcloud firestore databases create \
  --database="(default)" \
  --location="$REGION" \
  --type=firestore-native
```

## 2. Create scoped service identities

```bash
gcloud iam service-accounts create risk-fleet-worker --display-name="Risk Fleet worker"
gcloud iam service-accounts create risk-fleet-ui --display-name="Risk Fleet UI"
gcloud iam service-accounts create risk-fleet-push --display-name="Risk Fleet PubSub push"

for ROLE in roles/datastore.user roles/aiplatform.user roles/logging.logWriter roles/pubsub.publisher; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$WORKER_SA" \
    --role="$ROLE"
done
```

The UI identity receives no Firestore or Vertex role. It records decisions and requests publication
only through the application API. The push identity receives no data role.

## 3. Build the single image

```bash
gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker \
  --location="$REGION"
gcloud builds submit --tag "$IMAGE" .
```

The image respects Cloud Run's injected `PORT`. `SERVICE_MODE=worker` starts FastAPI/Uvicorn;
`SERVICE_MODE=ui` starts Streamlit.

## 4. Deploy the private worker

```bash
gcloud run deploy "$WORKER_SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$WORKER_SA" \
  --no-allow-unauthenticated \
  --timeout=600 \
  --set-env-vars="SERVICE_MODE=worker,APP_ENV=cloud,STATE_STORE=firestore,FIRESTORE_DATABASE=(default),PUBSUB_TOPIC=$TOPIC,RISK_FLEET_PROVIDER=gemini,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,RISK_FLEET_DETERMINISTIC_FALLBACK=false,DEMO_RESET_ENABLED=true"

export WORKER_URL="$(gcloud run services describe "$WORKER_SERVICE" \
  --region="$REGION" --format='value(status.url)')"

gcloud run services add-iam-policy-binding "$WORKER_SERVICE" \
  --region="$REGION" \
  --member="serviceAccount:$UI_SA" \
  --role="roles/run.invoker"
gcloud run services add-iam-policy-binding "$WORKER_SERVICE" \
  --region="$REGION" \
  --member="serviceAccount:$PUSH_SA" \
  --role="roles/run.invoker"
```

Vertex AI is the sole cloud credential path: Application Default Credentials come from the worker
service identity. No API key or secret is required. If an API-key path is intentionally chosen later,
inject it as a Cloud Run secret rather than an environment value in source control.

## 5. Create authenticated Pub/Sub push

```bash
gcloud pubsub topics create "$TOPIC"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"

gcloud pubsub subscriptions create "$SUBSCRIPTION" \
  --topic="$TOPIC" \
  --push-endpoint="$WORKER_URL/pubsub/push" \
  --push-auth-service-account="$PUSH_SA" \
  --push-auth-token-audience="$WORKER_URL" \
  --ack-deadline=600 \
  --min-retry-delay=10s \
  --max-retry-delay=600s
```

Cloud Run validates the push identity before FastAPI sees the request. Malformed or unknown event
payloads return `400`; valid processing returns `2xx`; infrastructure or workflow failures return
non-`2xx` and are redelivered.

## 6. Deploy the Streamlit UI

```bash
gcloud run deploy "$UI_SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$UI_SA" \
  --allow-unauthenticated \
  --set-env-vars="SERVICE_MODE=ui,APP_ENV=cloud,STATE_STORE=firestore,PUBSUB_TOPIC=$TOPIC,RISK_FLEET_PROVIDER=gemini,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,WORKER_URL=$WORKER_URL,WORKER_AUTH=true,DEMO_RESET_ENABLED=true"

gcloud run services describe "$UI_SERVICE" --region="$REGION" --format='value(status.url)'
```

The UI is public here solely to give hackathon judges a direct URL. The worker and all data actions
remain authenticated. For a controlled audience, replace `--allow-unauthenticated` with an
organization-approved access layer such as Identity-Aware Proxy or explicit Cloud Run invokers.

## 7. Live smoke test

Reset the known synthetic record from the UI, then publish the versioned event twice:

```bash
gcloud pubsub topics publish "$TOPIC" \
  --message='{"schema_version":"1","event_id":"risk-event-acme-001","scenario_id":"acme-synthetic-v1"}'
gcloud pubsub topics publish "$TOPIC" \
  --message='{"schema_version":"1","event_id":"risk-event-acme-001","scenario_id":"acme-synthetic-v1"}'
```

Inspect the Cloud Run logs and Firestore records:

```bash
gcloud run services logs read "$WORKER_SERVICE" --region="$REGION" --limit=100
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$WORKER_URL/investigations/investigation-acme-001"
```

Open Firestore Studio in the Google Cloud console to inspect the independently queryable claim and
audit documents.

Confirm in the console or UI:

1. one `event_receipts/risk-event-acme-001` document is `completed`;
2. one investigation is at `AWAITING_HUMAN_REVIEW`;
3. `claims/claim-001` is rejected at 4.1x;
4. `claims/claim-002` is verified at 3.8x and supersedes `claim-001`;
5. the audit sequence is contiguous;
6. model-call metadata names Gemini/ADK;
7. a UI human decision persists and changes lifecycle atomically.

Visible video proof can use the UI `.run.app` URL, the two Cloud Run service pages, the Pub/Sub
subscription, the Firestore claim documents, and the structured `event_completed`/`duplicate_event`
Cloud Logging entries. Record only the already-validated resources and redact project numbers,
account identities, and unrelated console data.

The locked `google-cloud-firestore==2.29.0` client expects an explicit database path. The repository's
Firestore adapter contains a narrowly isolated compatibility shim for the `(default)` database; no
manual source edit or deployment-time patch is required.

## Consistency and failure model

`event_receipts/{event_id}` is acquired in a Firestore transaction with a ten-minute processing
lease. A completed receipt reuses the existing investigation. A live processing lease acknowledges a
duplicate without running reasoning. A stale lease may be reclaimed. Successful handling writes the
complete investigation and marks the receipt completed; a failed attempt removes only the known ACME
partial record and releases its own receipt so Pub/Sub can retry.

Human decisions use a Firestore transaction that reads the canonical root state, applies the existing
lifecycle/capability rules, appends the next audit sequence, and writes the snapshot. The first valid
terminal decision wins. A later transition is rejected, persisted as `human_decision_rejected`, and
returned as HTTP `409`.

Reset is hard-coded to the ACME event/investigation IDs and returns `409` while an unexpired event
processing lease is active. It cannot enumerate or delete unrelated data.

Firestore unavailability yields a non-success request and no approval. Gemini failure follows the
existing bounded provider policy and escalates safely without bypassing human review. There is no
trade or recommendation-execution endpoint.
