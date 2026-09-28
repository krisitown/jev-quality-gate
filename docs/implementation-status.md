# Implementation status

Status: first Python implementation, 2026-09-29. The revision 0.2 design remains the target contract; this file records what is actually exercised.

Implemented: strict config/YAML validation, branch/merge-base comparison, complete path inventory, bounded diff chunking and reconstruction, sequential policy/chunk/reconciliation scheduling, typed choice Gateway calls, at most one 503 retry, concrete request menus, exact Git file/search/document retrieval, optional pinned Ripwire 0.6.5 callers/callees from a committed snapshot, confidence thresholds, coverage-aware aggregation, CI exit mapping, durable Evidence Packs, inspect, and offline protocol replay. The repository includes a GitHub Actions template and its own test workflow.

Mechanism tests use temporary committed branches, fake Gateway responses, and a verified Ripwire executable fixture. The full suite passes with Ripwire enabled (23 tests), and an independent mock-data smoke test exercised six branch-diff chunks plus reconciliation, offline replay, and a Gateway authentication failure that stopped after one request while preserving the Evidence Pack. These are engineering tests, not accuracy evidence. The illustrative demo policy is uncalibrated. Gate mode requires non-null policy thresholds and a calibration ID, but the tool cannot itself certify that a profile was calibrated against human labels or held-out cases. The operator must supply a trusted control checkout and pin the exact tool, provider, policy, model, and target revisions.

Known limitations to validate before formal use:

- Ripwire relation output is heuristic, may be incomplete, and only callers/callees JSON operations passed current fixtures. No implementation/test-association/dependency-neighborhood capability is advertised.
- The Gateway alias does not provide an immutable model weight digest here. No live endpoint check has been performed for this workspace; context and rate limits remain unmeasured.
- Token enforcement uses the conservative UTF-8 byte count of the serialized request, while native usage is recorded when provided. This bound and real server behavior need integration validation before a release gate is trusted.
- Candidate menu coverage, policy thresholds, cross-chunk sensitivity, repair usefulness, and false-alarm/miss rates require the planned human-labelled corpus. The 30-story campaign remains unfrozen.
- Protocol replay verifies saved answers, aggregates, and CI mapping; it does not reconstruct external Git objects or rerun Ripwire. Preserve source repositories or Git bundles with formal packs.

Changes from the draft: `control_bundle.root` may be relative to its trusted config file for portable checkouts. The only Ripwire capability currently enabled is callers/callees, after executable fixture testing. The public experiment policy folder remains empty until its application constitution and labels exist.
