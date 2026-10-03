# Jev through Vercel AI Gateway

Status: design revision 0.2. Transport selected by the user and checked against existing watchdog/exploration code by GPT-6 Luna. Live synthetic and public-PR evaluations have now exercised this transport; see the [validation report](../validation/public-prs-2026-09-30.md).

## Selected integration

Use a small Python HTTP adapter, initially matching the existing projects:

- Endpoint: `POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`.
- Model: `typesafe-ai/jev`.
- Headers: JSON content/accept and `Authorization: Bearer` from `AI_GATEWAY_API_KEY`.
- Body: `model`, shared `state`, and keyed `questions` with typed criteria.
- Answers: native `choice`, `noul`, and optionally `score`; no generated explanations or arbitrary JSON schema generation.

The official [TypeSafe compatibility documentation](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe) describes this transport. The newer [evaluation endpoint](https://vercel.com/docs/ai-gateway/modalities/evaluation) uses `/v1/evaluate` and different names such as boolean/probability. Preserve the existing native contract in v0; switching transport is a versioned adapter change. Jev evaluation is not an OpenAI-compatible chat-completions call.

```json
{
  "model": "typesafe-ai/jev",
  "state": "Policy, trusted conventions, chunk evidence, and concrete request candidates supplied by jev-ci.",
  "questions": {
    "disposition": {
      "type": "choice",
      "instructions": "Evaluate the supplied bounded policy question using the supplied evidence and declared limitations.",
      "criteria": {
        "compliant": "Evidence is sufficient and the in-scope change follows the policy.",
        "violation": "Evidence is sufficient to identify an introduced or worsened violation.",
        "need_more_evidence": "The policy is clear but a specific repository fact is missing.",
        "policy_ambiguous": "The policy does not establish a reliable answer even if code facts are understood.",
        "uncertain": "A reliable decision is not possible from available evidence or feasible requests."
      }
    }
  }
}
```

This body is a design example, not a submitted request. The controller can add request-selection and evidence-support questions as described in [the protocol](evaluation-protocol.md). It turns typed answers into state transitions; raw API output is never represented as a generated reasoning trace.

## Adapter behavior and normalization

`evaluate(state, questions, deadline, limits) -> TypedEvaluation` uses bounded, non-streaming HTTP JSON. Validate the exact requested answer IDs, permitted choice IDs, finite scores/probabilities, required numeric fields, and response size. Preserve raw choice probabilities and native confidence separately. A `noul` value is the supplied probability for that proposition, not a confidence score for another question. Derived selected-option probability is explicitly labelled. Use the declared choice, without recomputing it from an argmax. Record score disagreement without invalidating the response. Do not manufacture missing fields or copy confidence from another answer.

Store safe response metadata, native `usage.input_tokens`/`output_tokens` when supplied, request/response sizes, latency, each attempted call, and routing/cost metadata when present. Unknown telemetry remains null with a reason. Do not record authorization headers, environment values, or raw request objects that include credentials. Hosted usage and monetary cost are measured separately from the local Qwen generation workload.

Use one shared deadline and budget across an initial request and at most one retry on HTTP 503 in v0, with a 500 ms backoff. Disable HTTP-library automatic retries. The structured native `max_tokens_exceeded` error (including JSON embedded in Gateway error strings) ends the unit as context-budget uncertainty without retry. Other errors are recorded; 401/403 is an authentication failure, not policy uncertainty. Timeout leaves an attempted call of unknown billing status; do not assume no cost. This intentionally differs from watchdog's three-retry limit. Do not send unsupported chat sampling/max-token parameters. Verify supported limits during integration validation.

Do not opt into model fallback or virtual-model routing. Record and check returned model/routing identity; a different evaluator invalidates the treatment unless explicitly versioned. Pin provider routing when supported and validated. If `typesafe-ai/jev` is an alias without an exposed immutable model revision, record that limitation and evaluation timestamps rather than inventing a weight digest.

## Credentials and portability

Public configuration refers only to `AI_GATEWAY_API_KEY`. CI injects it using its secret store. Local use can explicitly opt into an ignored dotenv file with `--env-file`; environment values take precedence and only configured credential variables are read. The implemented loader uses a dotenv library, never shell-sources the file. No implicit loading from a candidate repository.

The research workspace may provision an ignored `.env.local` with mode 0600 from the user-authorized existing credential source. It is not part of the tool distribution, policy repository, Evidence Pack, or public example set. Live requests verified this workspace's entitlement during engineering validation; that does not guarantee future key validity or availability. Source paths and code audit references belong in the parent research record, not in this portable adapter.

## Validation before formal use

Check native choice/noul fixtures, probabilities/confidence semantics, input/context limits, unknown field behavior, usage capture, routing identity, malformed responses, 503 retry bounds, timeouts, and secret-free traces. Confirm candidate selection and template-based feedback are useful enough for repairs. Thresholds from watchdog/router solve different questions and must not be copied into CI policies.
