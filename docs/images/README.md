# Screenshot capture plan

Store final, genuine captures in this directory. Do not fabricate screens or include private worker
credentials, account menus, project numbers, personal email addresses, unrelated resources, or
unredacted notification content.

1. `01-portfolio-trigger.png` — Portfolio view showing ACME Corp, $75m exposure, 120bp → 210bp,
   +90bp, HIGH severity, cloud mode, and the event trigger.
2. `02-verification-correction.png` — Evidence & Verification showing upstream 4.1x, authoritative
   filing/tool 3.8x, `claim-001` REJECTED, `claim-002` VERIFIED, supersession, and the permission denial.
3. `03-human-gate.png` — Decision view showing Machine Verification PASSED, Risk RED, Governance
   HUMAN_REVIEW_REQUIRED, and Lifecycle AWAITING_HUMAN_REVIEW.
4. `04-architecture.png` — a readable render of the Mermaid diagram in `docs/architecture.md`.
5. `05-google-cloud-proof.png` — optional Cloud Run view showing the worker and UI deployments, with
   sensitive or unrelated console fields cropped or redacted.

Capture the first three only from a successful live run. Check every image at its intended Devpost
display size before committing it.
