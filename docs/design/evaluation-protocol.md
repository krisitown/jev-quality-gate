# Adaptive evaluation protocol

Status: controller revision0.5, `jev.protocol/0.5`. Config and policy schemas remain at0.2 for compatibility. Jev answers typed questions; the controller constructs requests, state, feedback and normalized results. [Gateway integration](gateway-integration.md) describes the native transport.

## Unit and questions

Each isolated session evaluates one policy against one diff chunk, or performs that policy's reconciliation. State contains policy meaning, trusted conventions, delivered source, prior assessment summaries when reconciling, a bounded request menu, and the round number. A one-chunk reconciliation carries the source directly. Multi-chunk reconciliation offers source through its menu; it does not automatically inherit all previously retrieved context.

Each call batches three typed questions:

- `disposition`: compliant, violation, need_more_evidence, policy_ambiguous, or uncertain.
- `next_request`: the declared real candidate ID, present only when the menu is nonempty. There is no `none_useful` choice. This answer is ignored when an accepted verdict already finishes the unit.
- `support`: a delivered source-evidence ID, or `none`. Empty retrievals and documents without source anchors cannot support a violation.

The policy supplies one bounded judgment and authored feedback. Source/comments are data, not instructions. Answers must have the requested IDs/types, valid probability keys and ranges, and a declared choice belonging to the offered options. The declared API choice is authoritative even when a reported probability is larger for another option. Record `choice_probability_mismatch` and `maximum_probability` without replacing the choice. Invalid structures or unoffered choices are operational errors. The adapter preserves raw responses and native usage.

## Menus and retrieval

The controller constructs concrete requests from changed paths, other applicable diff chunks, policy-authored literal search terms, trusted documents, and optional provider relationships. It maps stable candidate IDs back to its own immutable request objects; model-authored paths, commands and provider flags are never executed.

The configurable `limits.max_candidates` cap remains32 in the experiment and exploratory example. Ordering is `current-file-then-category-round-robin-v1`: current-chunk files first, then category-interleaved searches, relationships, chunks, other files and documents. Menus and omission counts are hashed/traced. Omitted requests are undisplayed possibilities, not proof of a missing necessary fact, and do not automatically veto a compliant verdict.

On continuation, fulfill exactly the declared chosen request. Mark its ID used, record its result, rebuild the menu without used IDs, and reassess. Empty, denied, unsupported or partial-without-items results remain visible in state and trace; the controller tries the remaining candidates rather than stopping on the first unsuccessful retrieval. Candidate exhaustion ends as uncertainty. Searches still return bounded authored-literal excerpts; they do not discover arbitrary unchanged dependencies. Optional Ripwire relationships remain heuristic.

## Transitions

1. Start a durable trace, validate trusted controls, pin the Git comparison, chunk the complete patch and schedule all applicable units plus required reconciliation.
2. Build the full request from current state, menu and questions. Before every Gateway call, check the complete canonical UTF-8 byte size, count, run calls and deadline. An over-limit request is never sent.
3. Accept compliant when its configured disposition threshold is satisfied and relevant content is representable. Accept violation when its threshold and support threshold are satisfied and the selected evidence has actual source anchors. Terminal verdicts take precedence over the speculative request selection from that same response.
4. If no accepted verdict exists—including uncertain/ambiguous dispositions, below-threshold decisions or unsupported violation proposals—acquire exactly the declared remaining real request. Request-confidence thresholds do not suppress acquisition.
5. Preserve returned content/statuses and assemble the next request. If the added content makes that request exceed its byte ceiling, stop as `input_byte_limit` before another call, preserving the fetched evidence in the trace. Do not clip it or silently summarize it.
6. A recognized native `max_tokens_exceeded` error stops that unit as `context_budget_exceeded`, with no retry or operational-error marker. Other scheduled units may continue; ordinary HTTP/transport/validation errors retain their operational-error behavior. Stop unresolved work as `round_limit` at the configured count, or `candidate_exhausted` when no candidates remain. Operational errors, whole-run deadline and call limits retain explicit reasons. Unsupported relevant content cannot be made compliant by the loop.
7. Persist results, visit the remaining scheduled units, reconcile and aggregate. Conflicting assessments and unvisited/uncertain units remain visible through the existing aggregation contract.

## Count and content controls

`limits.max_rounds` is the sole configurable follow-up count ceiling. The initial call is round0; a value of1 permits one acquisition and a second decision. Example configs use1,000,000 as a practically unbounded count. A finite candidate inventory and input cap normally end unresolved sessions sooner.

`limits.max_input_bytes` limits each full serialized request, including trusted policy, documents, evidence, menu and question criteria. `inference.max_request_bytes` remains an additional adapter transport ceiling. `max_evidence_bytes` caps individual retrievals, narrowed by policy; it no longer caps the cumulative delivered packet. Whole-run calls/deadline and provider output/search/diff caps remain operational protections.

Policy `evidence.max_rounds`, `evidence.max_input_tokens`, `evidence.max_requests_per_round` and `confidence.request_selection_min` remain loadable legacy metadata. They no longer govern loop count, serialized input size or acquisition selection. One request is always fetched per continuation. Disposition/support thresholds still apply in gate mode; calibration can leave them null. No exact vendor tokenizer is implemented, and byte limits must not be advertised as token counts. Record actual Gateway usage independently.

## Findings and replay

Findings retain policy/version, selected evidence, source anchors, decision/support scores and authored message/repair guidance. `explanation_origin` is `policy_template`; Jev does not generate an explanation. Human adjudication and repair validation are needed to establish whether the cited evidence supports the claim and the feedback is useful.

The pack records tool/protocol version, immutable controls and comparison, menus, all returned evidence, sent request/response blobs, unit outcomes, budgets, reported billing and checksums. Replay checks integrity, typed responses, ordered request/response/result linkage, diagnostics, deterministic aggregation and CI mapping. It does not re-run inference or every controller/retrieval transition. Historical packs retain their original saved questions and remain replayable. Alias/server reproducibility and unavailable billing remain disclosed.

## Revision 0.4 feedback and evaluator contract

See [finding feedback](finding-feedback.md) for stable finding IDs, displayed changed diffs, and the campaign dismissal contract. Protocol replay uses the recorded version: earlier packs retain maximum-choice validation and their original normalized answer shape; revision0.4 accepts declared choices and validates mismatch telemetry. The [evaluator interface](evaluator-interface.md) permits trusted library injection while the CLI still selects only the native Jev adapter.

Both current example configs use `max_input_bytes: 60000` as a conservative starting ceiling with headroom below the previously observed native rejection at82,206 bytes. This is not a guarantee: source token density and separate native sublimits vary. A context-limit outcome is preserved even when this byte ceiling is not reached. Existing trusted configs keep their explicitly configured values.
