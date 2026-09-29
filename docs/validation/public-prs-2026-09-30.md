# Public PR engineering validation — 2026-09-30

Jev CI 0.2.0 completed live Gateway evaluation of three fixed public pull requests from different languages and sizes. Every applicable chunk and required reconciliation ran, all three runs finished without operational errors, and all three Evidence Packs passed offline verification. Flask was compliant; Gin and Svelte remained uncertain. This validates the integration and conservative completion behavior, not review accuracy or a calibrated release gate.

## Fixed cases and final outcomes

| Public PR | Language | Changed lines: total / scoped source and tests | Applicable chunks | Final policy outcome | Calls | Seconds | Reported USD |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| [pallets/flask #6145](https://github.com/pallets/flask/pull/6145) | Python | 25 / 25 | 2 | compliant | 5 | 3.19 | 0.000698334 |
| [gin-gonic/gin #4806](https://github.com/gin-gonic/gin/pull/4806) | Go | 156 / 156 | 5 | uncertain | 9 | 6.136 | 0.001644090 |
| [sveltejs/svelte #18535](https://github.com/sveltejs/svelte/pull/18535) | JavaScript/TypeScript (Svelte) | 2269 / 705 | 30 | uncertain | 55 | 33.265 | 0.016634100 |

Changed lines means additions plus deletions. Svelte has 46 changed files and 53 total diff chunks. Its actual frozen policy scope covers 705 lines across 30 files (271 implementation, 434 tests). The broader source/test group contains 741 lines; 36 of those fall outside the authored glob scope. The full 2,269-line patch also includes 19 public type-declaration lines, five changeset lines, 1,383 devcontainer lines, 105 notebook/checkpoint lines, 16 documentation lines, and empty scratch files. The complete patch was inventoried and chunked; policy scope deliberately selects reactive-state implementation and related tests. Gin has six total diff chunks, five applicable to its source/test policy. No clipped prefix was treated as a complete branch.

The final runs made 69 Gateway calls and reported $0.018976524 in total. Native input/output token counts and per-call reporting counts are in the [machine-readable record](public-prs-2026-09-30.json). These are reported costs for these runs, not a pricing guarantee. Failed-call billing can be unknown.

## Selection, controls, and provenance

A Luna agent selected these cases and authored the policies before seeing Jev outputs. The cases were retained through adverse outcomes; policies, scope, thresholds, and config budgets were not adjusted after results. Exact head, stated base, unique merge base, source license, and control-file hashes are committed in [cases.json](../../validation/public_prs/cases.json). Each [control bundle](../../validation/public_prs/controls/) contains the frozen YAML policy, trusted convention, and config. The controls use calibration mode, null thresholds, and report-only actions. Source-based expectations from an independent agent are engineering observations, not human labels.

The checked-out PR repositories were stored in a temporary folder. Only immutable Git objects and the pinned trusted Ripwire executable were read; no candidate builds, tests, hooks, or application code were executed. Source repositories retain their own licenses (Flask BSD-3-Clause; Gin and Svelte MIT). Full Evidence Packs contain third-party source and remain local, outside the published tool; the public record contains metrics, provenance, and outcome diagnostics. Evaluation timestamps are preserved in UTC; this report date is local Europe/Sofia.

## What the outcomes mean

- **Flask:** both scoped chunks and reconciliation were compliant. Two exact committed-file requests supplied additional context. The independent source review found the explicit `PathLike` conversion and dataclass-class rejection consistent with the authored policy.
- **Gin:** all five scoped chunks were compliant, but reconciliation selected missing evidence and no useful next request. The controller returned `unit_uncertainty`, with the diagnostic `candidate_gap`; zero chunks were unvisited. An unresolved reconciliation cannot produce branch-level compliance.
- **Svelte:** all 30 scoped chunks and reconciliation were visited. Its final diagnostics were 23 `candidate_gap`, six `candidate_menu_incomplete`, and two `model_uncertain`. The bounded menu still had omissions; conservative uncertainty remained. No actionable violation finding was produced. This is limited review utility under these controls, not evidence that the PR is defect-free.

All three had zero findings and null aggregate confidence. The native choices, probabilities, evidence requests, and uncertainty details are preserved locally. A successful report-only exit means the configured CI action allowed the run; it does not establish code correctness.

## Adverse observations and repairs

Initial runs completed as compliant/uncertain/uncertain and passed verification. Svelte exposed request-menu starvation: changed files filled the menu before authored searches could appear. The controller now prioritizes current-file context and shares remaining slots across request categories; omissions remain visible and continue to prevent unsupported compliance. A regression covers large changed-file inventories.

The next Svelte attempt failed after 14 of 30 scoped chunks. A native tied choice serialized probabilities as `0.19999999999999998` and `0.2`; an exact floating-point equality check rejected it. The validator now accepts only rounding differences within an absolute `1e-12`, preserving the native choice and raw probabilities. Tests still reject materially non-maximal choices. The failed pack preserves successful earlier rounds, actual call counts, and unfinished scope. It passed integrity/linkage verification as a recorded error. The final run completed all scope after this fix.

Aggregate reason version 2 separates `unit_uncertainty` from `incomplete_coverage`. Human reports show the actual per-unit reasons; earlier reason-version-1 packs retain their historical labels and remain verifiable. All initial, failed, and final attempt metrics are included in the public JSON record; no failed attempt was deleted or represented as a source judgment.

Live synthetic branches separately exercised compliant JSON parsing, a direct untrusted-input `eval` violation, and an indirect helper violation requiring adaptive file/search retrieval. All three completed and verified. These controlled fixtures establish mechanism behavior; they do not substitute for real review labels.

## Ripwire and operational checks

A verified Ripwire 0.6.5 executable materialized Gin's exact head from committed blobs and successfully queried callees of `routergroup.go:QUERY` (one returned item) and callers of `routergroup.go:handle` (12 returned items). Its map showed 200 of 2,306 symbols; coverage was explicitly partial. Snapshot/query preparation took 0.146 seconds in this local run. A supplemental live Gin evaluation with Ripwire enabled completed as uncertain and its pack verified. This proves preparation and query compatibility on real Go source; it does not establish semantic graph completeness or prove that Jev selected graph evidence.

The adapter records Gateway routing/model identity and decimal reported cost, enforces total HTTP and shared run deadlines, and treats malformed responses as operational failures. Git blob scans use bounded batch processes rather than one process per file. Exact searches disclose skipped binary/oversized content and truncated long-line excerpts. Terminal and Markdown reports escape control characters and markup. Offline verification checks checksums, typed answers, ordered prompt/attempt/response/result linkage, diagnostics, and deterministic aggregation/CI mapping. Its declared scope is `integrity_linkage_and_deterministic_aggregation`; it does not re-execute all controller transitions or external retrieval, and checksums do not prove authenticity if an entire archive is replaced.

The recorded size was corrected from 741 (the broader source/test group) to 705 after checking every changed path against the frozen policy matcher. Policy bytes and scope were kept unchanged; this corrects metadata, not the evaluated treatment.

The complete local suite passed 56 tests with the verified Ripwire executable enabled. Three additional harness error-propagation cases then passed (six harness tests total), bringing the final suite to 59 tests. Ruff lint/format checks passed. A wheel was built and installed in a clean environment outside the source checkout; all three frozen controls validated and all three release packs verified with that installed CLI. The published harness also prepared all three exact public snapshots successfully without inference. Credential scans found no key leaks.

## Reproduce and interpret

Follow the [public PR harness instructions](../../validation/public_prs/README.md). Preparation fetches frozen commits and verifies merge bases and hash-bound controls; `--evaluate` explicitly makes live paid Gateway calls. Each invocation uses a new output directory, preserving previous attempts. Future model-alias changes can produce different decisions.

Remaining work is human-labelled policy calibration, candidate-menu recall/selection and support checks, chunk-order/size sensitivity, repair usefulness, and false-alarm/miss measurement. Immutable model weights, maximum server context, and rate limits were not established here. The separate application and 30-story experiment remain unfrozen and unstarted.
