# Gemini and Google ADK integration

## Provider modes

`OfflineReasoningProvider` is the default and does not inspect credentials or call a model. It
guarantees the approved seeded path: upstream 4.1x is rejected, deterministic filing/tool support
establishes 3.8x, the old claim remains immutable, and governance requires human review.

`GeminiAdkProvider` is selected only with `--provider gemini`. Its default model is
`gemini-3.7-flash`; `GEMINI_MODEL` can override it. The model is used for bounded reasoning, not for
arithmetic, permission decisions, evidence registration, verification, governance, or approval.

## ADK flow

1. The deterministic control plane registers evidence and executes authorized tools through
   `ToolGateway`. Credit's deliberate portfolio request remains denied and audited.
2. ADK runs Credit and Market concurrently.
3. Investigator consumes both strict outputs and produces a synthesis.
4. Challenger produces non-authoritative challenges against proposal IDs.
5. The adapter validates every reference and assigns canonical authors and object IDs.
6. The deterministic Verifier and governance engine remain final machine authorities.

The agents use `output_schema` and `output_key`; they have no ADK tools. All tool access remains at
the existing role-bound gateway.

## Prompts and output trust

Prompts live in `src/institutional_risk_fleet/prompts` and have role-specific `v1` versions. Output
models forbid unknown fields. A model cannot self-assign authorship or submit verifier status. The
adapter rejects unknown evidence IDs, tool-execution IDs, recommendation premises, Challenger
targets, and unsuccessful tool results before canonical mutation.

An honest Gemini response may notice the filing/upstream discrepancy and propose the supported 3.8x
value on the first pass. The workflow then verifies it without manufacturing a 4.1x failure or a
revision. Offline mode intentionally retains the frozen acceptance path.

## Failure and metadata policy

Each role call can record provider/model ID, prompt version, request ID, start/end time, latency,
validation result, retry count, fallback flag, optional input/output/total tokens, and error type.
Audit events cover request, response, validation failure, retry, provider failure, fallback, and role
completion. Credentials and hidden reasoning are excluded.

Timeout and retry counts are bounded by `GEMINI_TIMEOUT_SECONDS` and `GEMINI_MAX_RETRIES`.
Deterministic fallback is off by default. It must be enabled with `--deterministic-fallback` or
`RISK_FLEET_DETERMINISTIC_FALLBACK=true`; its use is explicitly audited. Without fallback, failure
safely enters required human review and never approves or trades.

## Live smoke prerequisites

Use either `GEMINI_API_KEY` for the Gemini API or the documented Google Cloud/Vertex credential
chain. Run:

```bash
uv run python -m institutional_risk_fleet.demo --provider gemini
```

The command does not make a human decision unless `--decision` is also supplied. Tests use fake
providers and never require network access.
