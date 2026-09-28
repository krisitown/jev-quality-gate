# YAML policy folders

Status: design revision 0.2, `jev.policy/0.2`. Users supply `--policies <folder>`; the folder can come from any checked-out policy repository. Policies ask one bounded engineering question and declare allowed evidence, examples/exceptions, and CI behavior. Internal records and API payloads remain JSON.

## Discovery and validation

Recursively discover `.yaml` and `.yml` files beneath the chosen root. Read one policy mapping per file in deterministic relative-path order, then schedule by stable policy ID. Reject an empty folder, duplicate IDs, duplicate YAML keys, multiple YAML documents, custom tags, aliases/merge keys, invalid field types, unknown fields, unsafe references, and symlinks escaping the root. Use a maintained safe YAML 1.2 loader; do not evaluate templates or execute YAML constructors. Non-policy Markdown files are ignored. Default limits are 64 KiB per policy and 2 MiB per folder, pending fixture validation.

Snapshot all selected policy bytes before inference. Record each relative path, raw SHA-256, normalized schema-valid JSON hash, and a pack hash over that ordered manifest. Record the external policy-repository revision when supplied; hashes are still required for local or modified folders. No policy is reloaded mid-run. Missing document bindings are errors; do not replace a policy's conventions with candidate-branch prose.

| Field | Meaning |
| --- | --- |
| `schema_version`, `id`, `version` | Supported schema, stable policy ID, explicit revision |
| `statement`, `question` | Convention and one bounded introduced-or-worsened question |
| `scope` | Relative path includes/excludes; no inferred exclusions |
| `interpretation` | Definitions, legitimate exceptions, and ambiguity criteria |
| `outcomes` | compliant, violation, uncertain |
| `documents` | Trusted named document bindings from root configuration |
| `aggregation` | requires_reconciliation by default; independent_chunks requires nonempty `aggregation.justification` documenting human review |
| `discovery` | Authored literal search terms used to construct candidate evidence requests |
| `evidence` | Permitted request types and limits, bounded by root ceilings |
| `confidence` | Decision/selection/support thresholds and metric/calibration identity |
| `feedback` | Authored violation message and repair guidance; plain text, never executable code |
| `ci` | Severity and outcome-to-action mapping |

## Example definition

This is an illustrative draft, not a validated experiment policy. Real document bindings, labels, and calibrated thresholds are required before gate mode.

```yaml
schema_version: jev.policy/0.2
id: business-decision-placement
version: 0.2.0-draft
statement: Eligibility decisions belong to the designated business-policy components.
question: Does this change introduce an eligibility decision outside those components?
scope:
  include: ["src/**"]
  exclude: []
  change_kind: introduced_or_worsened
interpretation:
  definitions:
    - The architecture document defines eligibility and designated component roles.
  exceptions:
    - Transport syntax validation that makes no eligibility decision is permitted.
  ambiguity:
    - The architecture document does not establish who owns this decision.
outcomes: [compliant, violation, uncertain]
documents: [architecture]
aggregation:
  mode: requires_reconciliation
discovery:
  search_terms: [eligibility, eligible]
evidence:
  allowed_requests: [GET_DIFF_CHUNK, GET_SYMBOL, GET_FILE, GET_CALLERS, GET_CALLEES, GET_IMPLEMENTATIONS, GET_TESTS, GET_DEPENDENCY_NEIGHBORHOOD, SEARCH_CODE, GET_DOCUMENT]
  max_rounds: 3
  max_requests_per_round: 3
  max_input_tokens: 20000
  max_evidence_bytes: 80000
confidence:
  metric: selected_probability
  compliant_min: null
  violation_min: null
  request_selection_min: null
  support_min: null
  calibration_id: null
feedback:
  violation: Review the reported change for an eligibility decision outside its designated owner.
  repair_guidance: Compare the cited code with the documented business-policy owner; move or delegate the decision while preserving behavior and tests.
ci:
  severity: warning
  compliant: report
  violation: warn
  uncertain: report
```

Jev answers typed questions; it does not author the feedback. `feedback` supplies a bounded explanation that the controller combines with selected source excerpts, document references, and the exact policy question. Do not claim a specific business rule or line was identified unless supporting selection established that location. Record chunk-level localization honestly.

The framework builds its fixed disposition/request/support questions from this schema; users cannot replace the protocol with giant persona prompts. `selected_probability` is the chosen category's supplied probability, distinct from a provider-specific `confidence` field. Preserve both when present. Null thresholds are legal for development/calibration only; gate mode requires a calibrated profile matching policy, model, candidate-generation strategy, and chunking settings.

## Public examples and experiment ownership

The future basic example set will be versioned in `jev-ci/examples/policies/`, with required architecture documents or explicit document-binding instructions and labelled examples. It can be published with the standalone GitHub repository. The experiment pins the exact policy pack revision/hash. Project-specific example files belong in this optional directory, never hard-coded in the evaluator. The research repository retains labels and treatment settings; the generic tool also accepts unrelated external policy repositories. Publication and the final 5–8 policies remain later work.

## Outcome semantics

Apply a policy to every applicable chunk, then use [aggregation](diff-chunking.md). Missing or ambiguous evidence cannot establish compliance. A bounded supported violation can coexist with partial overall coverage. No unsuccessful search alone proves an abstraction or duplicate is absent. Human-labelled validation must test cross-file interactions, candidate-menu omissions, and exceptions.
