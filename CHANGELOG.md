# Changelog

## 0.5.0 — 2026-10-03

Every new Evidence Pack now includes a self-contained HTML findings report for campaign spot checks. Offline exports can also review historical packs without making new model calls.

- Add `report.html` to new packs, covered by their final checksums.
- Add `jev-ci report --pack ... --output ...` to export saved results outside the sealed pack without changing original artifacts.
- Show policy and finding navigation, recorded outcome/action, colored unified diffs with old/new line numbers, cited source locations, authored repair guidance, selected scores, supporting evidence, and expandable typed decision rounds.
- Highlight precise rows only when source anchors identify a matching line and snapshot. File/chunk anchors remain scope markers; continuation chunks do not invent line numbers.
- Present uncertainty and operational failures explicitly, alongside available call/token/cost metadata. Scores are not labelled as accuracy.
- Bundle all styling; reports work offline without scripts or external assets. Escape source/model text and disallow active content.

Policy meaning, inference, config/feedback schemas and protocol0.4 remain unchanged. This release is presentation only; HTML inspection does not itself verify finding correctness, archive integrity, or record campaign dismissals.

## 0.4.0 — 2026-10-03

Coding agents can inspect a consistent finding packet and later record fix/dismiss/unresolved decisions in a campaign harness. Native answer disagreements and context exhaustion no longer unnecessarily abort otherwise usable runs.

- Honor the API's declared choice for disposition, evidence request and support. Keep structural/option/probability validation and configured disposition/support thresholds. Preserve `choice_probability_mismatch`, maximum and selected scores plus event-level mismatch names.
- Add content-based `finding_id`, one-sentence `policy_statement` and `related_diff` to findings; show these with support references in terminal and Markdown reports. Preserve source localization as bounded evidence, without claiming precise causal lines.
- Recognize structured native `max_tokens_exceeded` errors, including Gateway-wrapped JSON strings; stop that unit as `context_budget_exceeded`, without retry or run-wide operational failure. Other units may continue. HTTP/authentication/transport and malformed-answer failures remain operational errors.
- Reduce the current demo/exploratory example input ceilings to60,000 bytes as conservative pilot guidance. Existing configured limits remain explicit; bytes are not exact tokens.
- Add a small `Evaluator` library interface and injection point with actual adapter/model provenance and encoded-request sizing. Missing probability scores remain null and cannot satisfy a non-null score threshold. No second LLM backend or new CLI backend option is included.
- Document a campaign-side dismissal contract; no permanent suppression or campaign runner is implemented here.

Migration: config and policy schemas remain0.2. New packs record `jev.protocol/0.4`; feedback is `jev.feedback/0.2` with additive finding fields. Protocol replay preserves the older maximum-choice validator and normalized shape for historical packs. The existing three policy YAMLs and32-candidate menu remain unchanged. The application and campaign are separate later work.

## 0.3.0 — 2026-10-02

Unresolved policy evaluations now acquire the highest-ranked remaining evidence request until an accepted verdict or a resource/candidate limit. This addresses early exits caused by `need_more_evidence` plus `none_useful` and stops the request menu from automatically vetoing otherwise compliant judgments.

- Remove `none_useful` from next-request choices. Accepted compliance and source-supported violation take precedence over speculative request selection.
- Continue uncertain and ambiguous assessments; skip and disclose unsuccessful retrievals rather than ending the session.
- Retain the configurable32-candidate experiment menu and record omissions separately from the verdict.
- Make root `limits.max_rounds` the sole follow-up count ceiling; example configs use1,000,000. Root `limits.max_input_bytes` caps each complete serialized request. Recheck it after retrieval and never send an over-limit packet.
- Retain operational call/deadline and provider caps. Treat evidence-size limits as individual retrieval limits rather than a cumulative loop-content ceiling.
- Fix source anchors for retrieved diff-chunk envelopes. Exclude empty or unanchored evidence from violation support choices.
- Include the three exploratory responsibility policies with their exact shared conventions and a runnable report-only control bundle.

Migration: policy `max_rounds`, `max_input_tokens`, `max_requests_per_round` and `request_selection_min` remain accepted legacy metadata. Configure count/input limits at the root; request-confidence thresholds no longer prevent acquisition. Calibrated disposition/support thresholds remain enforced. Byte ceilings are explicit; no exact vendor-token count is claimed. Config/policy schema IDs remain0.2. Historical evidence packs retain their original questions and replay contract.

Engineering checks exercise terminal-verdict precedence, all unresolved dispositions, menu omissions, count and content exhaustion, empty retrieval progression, candidate exhaustion, source support and replay. Experimental accuracy and repair usefulness require separately reviewed labels and results.
