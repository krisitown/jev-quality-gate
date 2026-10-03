# Finding feedback and campaign review

Status: implemented finding output in0.4; campaign dismissal handling is a consumer contract for the later pilot.

`feedback.json` (`jev.feedback/0.2`) retains raw evaluator findings and uncertainty. Each finding adds:

| Field | Meaning |
| --- | --- |
| `finding_id` | Content-based SHA-256 identity for conservative repeated-finding tracking |
| `policy_id`, `policy_version`, `policy_statement` | Policy identity and its authored one-sentence rule |
| `related_diff` | In-scope changed diff envelopes delivered in this unit or carried by prior findings |
| `evidence_id`, `evidence`, `source_anchors` | Selected supporting evidence, its preserved content, and honest source localization |
| `message`, `repair_guidance` | Policy-authored claim and suggested investigation/repair |

The terminal summary and `report.md` display the ID, rule, related diff, support reference and source anchors. The JSON evidence is self-contained; use `evaluations/<unit_id>/result.json` and request/response blobs for deeper investigation. A related diff identifies bounded changed scope, not a guaranteed causal line or an independently proven defect. Jev does not generate free-form explanations.

Identity hashes the policy bytes, bound convention-document hashes, normalized related diffs, selected support and all observed delivered evidence. Run/unit/request/chunk IDs, commit IDs, diff offsets and verdict/support scores are excluded. Evidence ordering does not affect the hash. The same delivered facts can keep their ID across unrelated commits or configuration changes; changed source, convention or policy reopens the finding with a new ID. Alternative retrieval/support choices can produce different IDs: this is conservative content tracking, not semantic defect deduplication. Do not suppress by policy name alone.

## Campaign consumer contract

The later harness should preserve the original finding and append a separate agent-review record. A minimal record contains `finding_id`, source commit/story/attempt, decision (`fix`, `dismiss`, `unresolved`), short reason, evidence references and resulting commit when applicable. A fix claim still needs verification. A dismissal must explain the legitimate exception, unchanged behavior or unsupported allegation and cite source evidence; it remains a dismissal in metrics, rather than becoming evaluator compliance.

Only suppress repeated repair prompts for an explicitly dismissed finding with the same ID. Reconsider when relevant observed evidence or policy changes. Retain all original results and review records for independent adjudication, including incorrectly dismissed true defects. No persistent policy-wide exemption is created. The current tool has no dismissal CLI/database and does not edit an aggregate or CI status in response to an agent's review.

Freeze a finite story repair/feedback cap in the campaign harness, separately from the evaluator's evidence-acquisition count. Unresolved or repeated findings cannot keep the coding agent in an endless repair loop. Dismissal does not waive failing build/tests or other deterministic checks. Uncertainty is retained as uncertainty and is not an instruction to change code. The exact cap and continuation rule are campaign-planning decisions.
