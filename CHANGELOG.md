# Changelog

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
