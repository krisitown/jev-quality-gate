# Evaluator library interface

Status: small extension seam implemented in0.4. Native Jev remains the only shipped backend and CLI configuration.

`jev_ci.evaluator.Evaluator` defines three operations:

- `identity`: actual adapter/model identity recorded in the pack, independently of the supplied configuration.
- `request_bytes(state, questions)`: complete encoded request size including transport wrappers. The controller checks this against the explicit input/transport byte caps before every call.
- `evaluate(state, questions, deadline, on_attempt)`: return normalized typed answers plus preserved raw response/telemetry; validate offered choices before returning.

Trusted library callers may supply `evaluator=` to `jev_ci.coordinator.evaluate`. With an injected implementation, the coordinator does not load a Jev credential or construct the native Gateway. The caller still supplies structurally valid trusted configuration; this does not add a candidate-controlled plugin mechanism or relax evidence/CI controls. Supplying `transport=` remains the native adapter's HTTP test hook.

The controller continues to own policies, menus, retrieval, support anchors, budgets, aggregation and authored feedback. Answers contain the declared `choice` and `selected_probability`. If an evaluator has no genuine probability score, use null. Null is accepted when the policy's threshold is null and cannot satisfy a configured score threshold. Never turn a model's prose or self-assessed confidence into a native probability distribution. Native Jev continues to require valid probability fields and model/routing identity.

Adapters must preserve the `started`, `received`, `validated` or terminal-error attempt lifecycle, consume the shared deadline, report unknown costs as null, and provide `raw_response` plus `telemetry`. Raise `ContextLimitError` for recognizable native input-context exhaustion, and `InferenceError` for ordinary operational/response failures. Other adapter identities are recorded without claiming they are Jev. The native adapter still rejects routing to a different evaluator.

Before adding an LLM backend, implement and test its typed-choice normalization, encoded-request preservation, credential/model validation and replay validator. The current protocol verifier understands native Jev responses only; library injection does not certify arbitrary-backend replay. A future campaign comparison must version the actual backend, use the same bounded questions/evidence/feedback and common operational rules, and explicitly handle unavailable scores. The interface is preparatory; no second-backend experiment has been run.
