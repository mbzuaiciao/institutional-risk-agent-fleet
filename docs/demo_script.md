# Demo script — target 3:40

Record one continuous normal-speed run where practical. Keep the browser at a readable zoom, prepare
the application and two Google Cloud proof tabs in advance, and do not navigate through account
menus. The timing below leaves 20 seconds of buffer under the four-minute limit.

| Time | Screen and action | Narration |
| --- | --- | --- |
| 0:00–0:25 | Open the title and Portfolio view. | “Institutional agents can investigate risk autonomously, but institutions cannot rely on model confidence alone. Material claims need evidence, calculations need lineage, permissions need enforcement, and consequential recommendations need a human boundary.” |
| 0:25–0:50 | Point to ACME Corp, the $75m exposure, 120bp → 210bp, +90bp, and HIGH severity. Select **Trigger Risk Event** once. | “This synthetic credit event is published through Pub/Sub and processed asynchronously. The user does not prompt or manually invoke individual agents.” |
| 0:50–1:25 | Move to Investigation. Show the Cloud/Gemini/ADK indicators and Credit, Market, Investigator, and Challenger progress. | “Gemini 3.7 Flash runs through Google ADK. Credit and Market analyze in parallel; Investigator synthesizes; Challenger probes the proposal. The model is not authoritative over permissions, arithmetic, verification, or approval.” |
| 1:25–2:25 | Open Evidence & Verification. Show 4.1x upstream, 3.8x filing, and 3.8x deterministic tool. Show `claim-001` REJECTED, `claim-002` VERIFIED, and `supersedes claim-001`. Then show the Credit Agent permission denial. | “The Verifier catches the discrepancy. It does not overwrite the error: the 4.1x claim remains rejected, while a new verified 3.8x claim explicitly supersedes it. The Credit Agent also attempted portfolio access without that capability. Code blocked and audited the request.” |
| 2:25–3:05 | Open Decision. Show Machine Verification PASSED, Risk RED, Governance HUMAN_REVIEW_REQUIRED, and Lifecycle AWAITING_HUMAN_REVIEW as separate fields. Point to reviewer and rationale; record an explicit decision only if rehearsed timing allows. | “Passing verification is not automatic approval. This remains a HIGH-severity event against $75m of exposure, so deterministic governance requires an explicit human decision.” |
| 3:05–3:35 | Show the `.run.app` address, then one prepared Cloud Run console tab containing the deployed worker and UI. Use Firestore or Pub/Sub only if it is already framed and readable. | “The public Streamlit interface and private worker run on Cloud Run. Authenticated Pub/Sub delivers work, Firestore preserves state and claim history, and Cloud Logging records execution.” |
| 3:35–3:40 | Return to the architecture diagram or application. Stop immediately after the close. | “Institutional Risk Agent Fleet lets Gemini investigate autonomously while deterministic controls decide what the institution can trust.” |

## Recording fallback

If live processing makes the normal-speed recording exceed four minutes, keep the run continuous and
remove optional narration first. If still necessary, apply one uniform speed-up to the genuine
continuous recording and place a visible disclosure such as “Continuous live run shown at 1.15×.”
Do not splice outcomes, hide failures, or alter application timing.
