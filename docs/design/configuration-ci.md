# Configuration and CI semantics

Status: design revision 0.2, `jev.config/0.2`. An executable now exists; see [implementation status](../implementation-status.md) for supported fields and remaining validation.

## Inputs and precedence

```text
jev-ci evaluate --repo <checkout> --source <branch-or-commit> --target <protected-target> --policies <yaml-folder> --config <trusted-config.json> --output <new-pack-directory>
jev-ci validate --config <trusted-config.json> --policies <yaml-folder>
jev-ci inspect --pack <pack-directory>
jev-ci replay --pack <pack-directory> --mode protocol
```

Local source/target defaults are HEAD and `refs/heads/main`; CI supplies pinned source/target commits after fetching them. Root settings remain JSON, policies are YAML. Explicit `--policies` overrides the config's optional `policy_dir`; in protected CI the runner chooses this path and validates expected pack identity. No input silently loads from candidate HEAD.

Precedence: safe built-in defaults, trusted root settings, restrictive per-policy overrides, then invocation identity/output paths. CLI cannot relax budgets or thresholds. Resolve policy document paths within declared trusted roots. `--env-file <trusted-local-file>` is an optional explicit local credential source; it cannot override policy or inference configuration. CI uses injected environment secrets.

## Root fields

Required fields: `schema_version`, `mode` (calibration/gate), `control_bundle`, `document_bindings`, `inference`, `providers`, `diff`, `limits`, and `ci`; `policy_dir` is optional when `--policies` is provided. Discovery produces a frozen policy-file manifest rather than requiring hand-written file lists. Reject unknown fields and duplicate/missing bindings.

`control_bundle` names immutable trusted documents/config and permitted roots. `document_bindings` map IDs to revision/path/hash/authority. `inference` selects `vercel-typesafe`, model `typesafe-ai/jev`, the verified Gateway endpoint, credential env name `AI_GATEWAY_API_KEY`, timeout, byte/question limits, and supported provider options. Do not assume chat sampling settings exist. See [Gateway integration](gateway-integration.md).

`providers` registers ordered pinned adapters, executable digests, capabilities, index identity, and settings. Candidate branches cannot supply executable plugins. `diff` contains every chunking/whole-patch cap in one place; see [diff chunking](diff-chunking.md). Other modules must consume those values, not duplicate constants.

`limits` contains per-unit (policy/chunk or reconciliation) limits, candidate/support-question caps, root policy-file byte limits, and run-wide caps. Existing development ceilings of 8 policies, 40 calls, 800,000 cumulative input tokens where countable, and 900 seconds/run are provisional; chunking can require larger explicitly configured budgets. Preflight checks the minimum scheduled work, reserves pending-unit budgets, and reports insufficient capacity. Exact server/tokenizer limits require adapter validation; hard byte/call/time limits always apply and estimates remain labelled. Policy count is configurable, not a hard-coded experiment assumption.

`ci` defines severity (info/warning/error), actions (report/warn/block), trusted control-change rules, and artifact retention. Operational failures cannot be mapped to success. Calibration mode records provisional outcomes; gate mode requires a compatible calibrated profile and complete required configuration. A basic public policy example is not automatically a calibrated release gate.

## Aggregation and exit codes

Aggregate units and reconciliation into policy results using the explicit coverage rules in [diff chunking](diff-chunking.md). Retain unit scores; never average them into branch confidence.

| Condition | Run status | Exit |
| --- | --- | --- |
| All applicable policies completed compliant, with explicit not-applicable counts | completed | 0 |
| Report/warn violations or report-only uncertainty | completed_with_findings | 0 |
| Any outcome configured to block | blocked | 1 |
| Operational/config/comparison/trace failure | error | 2 |

Error takes precedence over block, while completed findings remain available. Exit 0 means configured enforcement allowed the result; it does not prove correctness. Unvisited chunks, candidate gaps, and failed reconciliation prevent a compliant policy aggregate. An uncertain -> block setting requests review; it is not a violation label.

## Pipeline and repair feedback

GitHub/GitLab wrappers supply the checkout, pinned refs, trusted policy folder/config, and secret; run the same CLI; upload artifacts even on failure; and preserve its exit status. The protected job executes a pinned tool/control version. Git cannot verify branch protection itself.

The tool emits `feedback.json` containing bounded policy claims, selected excerpts, source anchors, raw/derived score identities, authored repair guidance, and coverage/uncertainty. Messages are templates, not prose generated by Jev. The experiment harness decides which findings trigger Qwen repair and preserves every attempt. Proposed treatment C uses warn/block violations; uncertainty is retained rather than treated as an instruction to modify code.

Detect and log changes to CI, policies, documents, tests, exclusions, and suppressions. Legitimate control changes require independently versioned approval; a candidate cannot make itself pass by weakening its own trusted evaluation. Platform workflow files will be implemented after the generic CLI works.
