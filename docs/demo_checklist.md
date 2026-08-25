# Demo recording and rehearsal checklist

The current [official rules](https://allthingsagentichackathon.devpost.com/rules) require a public
English-language or English-subtitled YouTube/Vimeo demonstration no longer than four minutes. Use
the script in [demo_script.md](demo_script.md) and target 3:30–3:50.

## Before recording

- [ ] Verify the deployed UI is reachable.
- [ ] Verify the private worker is healthy through the UI or an authenticated check.
- [ ] Verify the Firestore demo state is reset.
- [ ] Verify the Pub/Sub subscription exists and authenticated push is healthy.
- [ ] Verify the Gemini/Vertex path is active.
- [ ] Verify deterministic fallback is not enabled unintentionally.
- [ ] Prepare the application, architecture, and one Cloud Run proof tab in presentation order.
- [ ] Hide unrelated tabs, bookmarks, account details, project numbers, and notifications where practical.
- [ ] Verify no credentials, tokens, private worker headers, or unrelated data are visible.
- [ ] Verify recording resolution, browser zoom, text readability, microphone, and audio level.
- [ ] Rehearse once with a visible timer before recording.

## Demo state

- [ ] ACME event is absent/reset and no processing lease is active.
- [ ] Portfolio view is ready with the cloud-mode badge visible.
- [ ] **Trigger Risk Event** is available.
- [ ] A synthetic reviewer name and concise rationale are ready if approval is shown.

## During recording

- [ ] Show the public application URL.
- [ ] Trigger the event exactly once; do not manually invoke agents.
- [ ] Show the Gemini 3.7 Flash and Google ADK labels.
- [ ] Show 4.1x rejected and 3.8x verified with supersession lineage.
- [ ] Show the Credit Agent permission denial.
- [ ] Show machine verification, risk, governance, lifecycle, and human status separately.
- [ ] Show unmistakable Google Cloud proof.
- [ ] Stay under four minutes.

## After recording

- [ ] Check duration, audio, pacing, and text readability.
- [ ] Confirm application operation and Google Cloud proof are visible.
- [ ] Confirm no sensitive data or private credentials appeared.
- [ ] Upload publicly to YouTube or Vimeo.
- [ ] Verify public playback while signed out or in an incognito window.
- [ ] Add the public video URL to the Devpost draft.

## Three-run rehearsal worksheet

Do not infer or backfill results. Complete this table using the live deployed system before the final
recording. Repository inspection alone cannot establish live timing or current cloud state.

| Run | Total duration | Event processing | Gemini successful | 4.1x → 3.8x correct | Permission denial | Human boundary | Navigation friction / notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Pending | Pending | Pending | Pending | Pending | Pending | — |
| 2 | Pending | Pending | Pending | Pending | Pending | Pending | — |
| 3 | Pending | Pending | Pending | Pending | Pending | Pending | — |

Prefer a normal-speed live run. If all clean runs are too long, first shorten narration and omit the
optional human submission. A uniformly accelerated continuous recording is a truthful fallback only
when the speed-up is visibly disclosed.
