# Adaptive evaluation protocol

Status: design revision 0.2, `jev.protocol/0.2`. This replaces the earlier assumption that Jev generates arbitrary JSON, explanations, or tool calls. Jev supplies typed choices/scores; the controller constructs requests and normalized records. See [Gateway integration](gateway-integration.md).

## Unit of work and normalized states

A unit evaluates one policy against one diff chunk, or performs that policy's required reconciliation. Each has an independent context, `evaluation_id`, `policy_id`, `unit_kind` (chunk/reconciliation), `chunk_id` (null for reconciliation), and `round`. A provider response is recorded unchanged, then normalized into one of three controller states:

| State | Meaning |
| --- | --- |
| `DECISION_READY` | A typed compliant/violation selection claims enough evidence; acceptance still requires thresholds, coverage, and support |
| `NEED_MORE_EVIDENCE` | A missing fact could be resolved by a selected allowed candidate request/bundle |
| `ABSTAIN` | Policy ambiguity, no useful available evidence path, exhausted resources, or unresolved uncertainty |

The framework's primary `disposition` choice has five fixed categories: `compliant`, `violation`, `need_more_evidence`, `policy_ambiguous`, and `uncertain`. Descriptions distinguish insufficient source facts from a convention that cannot establish an answer. These are protocol choices around the same bounded policy question, not new architecture policies.

## Candidate-driven context acquisition

`context.py` constructs a bounded menu of concrete authorized requests using changed paths/symbols, provider-reported relationships, known evidence IDs, related chunk IDs, and policy-authored literal search terms. It gathers candidate locations only; it does not decide compliance. It uses existing provider metadata and no custom language parser.

Each menu entry has a stable candidate ID, missing-fact description, expected resource limits, and 1–3 fully instantiated typed requests. Jev selects an ID via a `next_request` choice that also offers `none_useful`. The controller maps that ID back to the immutable request objects. It never executes model-authored paths, code, shell commands, or provider flags. No generative discovery model is introduced in v0.

The menu is bounded (proposed maximum 12 entries), deterministically ordered and hashed. The implemented ordering is versioned as `current-file-then-category-round-robin-v1`: current-chunk files first, then one candidate at a time from authored searches, symbol relationships, other applicable chunks, remaining changed files, and documents. Large file or symbol inventories cannot monopolize all menu slots. Within a category, source inventory order remains deterministic. Omissions still prevent unsupported compliance. Record candidates excluded by count/scope/capability. A missing candidate is a limitation, not evidence that the fact does not exist. If no shown option is useful, return `uncertain: candidate_gap`; calibration will determine whether paging or a richer discovery adapter is necessary. Candidate-menu recall is a separate metric.

The first request can batch disposition, next-request selection, and bounded supporting-evidence questions against the same state. Selection questions name framework-owned IDs and always allow no useful support. Native `noul` (boolean-probability) support questions apply to already delivered excerpt IDs, not unseen code. A sufficiently selected useful request takes precedence over a proposed compliant/violation/uncertain conclusion, so missing evidence is acquired before accepting that conclusion. Policy ambiguity is terminal. Preserve all raw answers for analysis.

## Transitions

1. Durably start a minimal run record, validate inputs, and snapshot policy/diff manifests. No applicable changes yields not_applicable without inference. Unrepresentable relevant changes create explicit uncertainty.
2. For each scheduled unit, build state from policy, trusted conventions, one chunk (or reconciliation index), delivered evidence, and candidate descriptions. Count serialized input; include protocol questions and criteria in resource accounting.
3. Call Jev through the configured Gateway adapter. Require all requested question IDs, permitted types, valid choices, numeric ranges, and valid probability mappings. Unknown choices, missing fields, or malformed responses are operational errors, subject to a single bounded transport retry where appropriate.
4. Accept ready/compliant only above its calibrated threshold and with complete known unit scope; require accepted reconciliation for branch-level compliance when configured. A ready/violation needs calibrated support selection anchored in actual evidence. Without support, retrieve feasible missing context or abstain; do not fabricate a rationale.
5. For missing evidence or a below-threshold ready answer, use a sufficiently supported `next_request` selection from that same response. Check authorization and all budgets before fulfillment. Append returned facts/statuses, then ask the same bounded question again. Confidence alone does not justify another call over unchanged evidence.
6. A policy-ambiguous answer ends the unit immediately. No useful candidate, repeated no-progress requests, unresolved conflicting answers, or exceeded limits produce uncertainty. Unknown/unsupported retrieval is evidence insufficiency; systemic provider failures remain errors.
7. Persist unit results, iterate all scheduled chunks, perform required reconciliation, and aggregate using [the chunking contract](diff-chunking.md). A detected violation does not hide unvisited units.

## Feedback and evidence

A normalized finding contains policy/version, chunk and source anchors, selected evidence IDs and support scores, decision scores, and authored message/repair guidance. `explanation_origin` is `policy_template`; it is never labelled a generated Jev explanation. Localization can be `chunk`, `hunk`, or `source_range`, based on what was actually selected. Human verification still determines whether these excerpts support the claim. Multiple actual defects inside one coarse finding are resolved in audited issue matching, not invented by the controller.

For abstention, record a reason code and template describing missing evidence, candidate gaps, or policy ambiguity. The controller owns these messages. Qwen repairs from the policy question, supplied evidence, and authored guidance; whether that is actionable enough is an explicit calibration requirement.

## Budgets and confidence

Proposed per-unit ceilings: 3 acquisition rounds, 3 requests/round, 5 Gateway calls including retries, 20,000 input tokens/call when countable, 100,000 cumulative input tokens, 80,000 unique evidence bytes, 20 search results/request, 16,000 bytes/provider response, 15 seconds/request, and 120 seconds/unit. Candidate/support question counts and serialized request bytes are also bounded. Chunk retrieval additionally obeys the central diff cap.

One initial call and up to three post-retrieval calls normally fit; reserve room for one permitted transport retry. Typed evaluation does not accept chat generation parameters by assumption. Output limits and tokenizer availability must match the actual adapter capabilities: hard byte, question, call, and time limits always apply, while unavailable exact token enforcement is disclosed. Formal gate use requires a documented, validated tokenizer/conservative upper-bound strategy or server limit; an estimate cannot be advertised as exact. Record returned usage independently of any local estimates.

Run-level limits cover all units and reconciliation, not one policy alone. The coordinator reserves remaining initial-unit/reconciliation budgets before extra rounds. Exhaustion marks remaining units uncertain with reason and counts. No implicit fallback to another model, unbounded retries, or summaries that erase missing evidence.

Calibrate selected-category probability, raw provider confidence, request selection, and support scores separately. Do not substitute one for another or assume universal probability calibration. A model alias without an immutable version is a disclosed reproducibility limitation.

## Results

A unit result includes schema/version, IDs, state/outcome/reason, typed answer scores and raw response reference, evidence/support selections, coverage/gaps, used budgets, timings, and trace reference. A policy aggregate includes constituent unit IDs, deduplicated findings, completed/uncertain/error/unvisited counts, reconciliation result, execution health, and CI action. Aggregate confidence is null; per-unit scores remain available. Systemic errors override CI success/block status while preserving completed judgments. Calibration runs retain provisional selections and cannot act as release gates.
