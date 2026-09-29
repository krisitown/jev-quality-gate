# Implementation status

Status: Jev CI 0.2.0, 2026-09-30. The [live validation report](validation/public-prs-2026-09-30.md) records exercised behavior and adverse outcomes. The revision 0.2 research design remains unfrozen.

Implemented: strict config/YAML validation; source-branch/merge-base comparison; complete path inventory; bounded diff chunking and reconstruction; sequential policy/chunk/reconciliation scheduling; native Jev choice Gateway integration with one 503 retry; necessary evidence acquisition before accepting a conclusion; deterministic bounded request menus shared across evidence categories; exact committed file/search/document retrieval; optional pinned Ripwire 0.6.5 caller/callee queries; confidence thresholds; coverage-aware aggregation and CI exit mapping; durable Evidence Packs; escaped terminal and Markdown reports; unit uncertainty diagnostics; inspect; and offline integrity/linkage plus aggregate verification. A GitHub Actions template, tested package workflow, and public-PR reproduction harness are included.

The live synthetic branches produced the expected compliant, direct-violation, and adaptive indirect-violation outcomes. Three public PRs from Python, Go, and JavaScript/TypeScript completed with all scoped chunks and reconciliation visited. Their final outcomes were compliant, uncertain, and uncertain. All packs verified. Independent Luna source/pack reviews found no spurious violation finding; this is engineering validation, not human-labelled accuracy evidence. Initial and failed attempts are retained in the validation record. Ripwire executable Java fixtures and direct real-Go queries both passed, with graph incompleteness disclosed.

The illustrative and public-validation policies are uncalibrated/report-only. Gate mode requires non-null thresholds and a calibration ID, but the tool cannot certify that a profile was calibrated against human labels or held-out cases. Operators supply a trusted control checkout and pin exact tool/provider/policy/target revisions. Native Gateway usage and decimal reported USD costs are retained; failed or missing billing reports remain unknown.

Remaining validation and scope limits:

- Ripwire evidence is heuristic and partial; only callers/callees are advertised. Implementation/test-association/dependency-neighborhood operations remain unsupported.
- Gateway alias identity and routing were verified live, but no immutable model weight digest was exposed. Maximum server context and rate limits remain unmeasured.
- Serialized UTF-8 request bytes provide a conservative token bound; native usage is recorded separately. The CLI does not use an exact vendor tokenizer.
- Candidate menu recall, threshold calibration, cross-chunk sensitivity, support accuracy, repair usefulness, and false-alarm/miss rates require the planned human-labelled corpus. Svelte's conservative uncertainty shows limited actionability under these controls.
- Protocol replay checks hashes, typed answers, request/response/result linkage, diagnostics, deterministic aggregates, and CI mapping. It does not re-execute every controller transition or rebuild Git/Ripwire state; archive replacement cannot be authenticated by checksums alone.
- A whole-run deadline bounds subprocesses and HTTP requests; forced process interruption can leave an unsealed pack, distinguishable from a clean finish.

The package is published at [krisitown/jev-quality-gate](https://github.com/krisitown/jev-quality-gate). The separate application, human-labelled calibration corpus, application-specific experiment policy pack, formal 30-story campaign, and research publication have not begun.
