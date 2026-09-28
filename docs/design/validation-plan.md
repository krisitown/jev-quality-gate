# Validation gates before formal use

Status: revision 0.2 future validation plan, not evidence of passed tests. Numerical performance/error targets must be registered before viewing held-out outcomes. Design review comes first.

## Layer 1: deterministic contracts

Validate policies/config/responses, enforce all counters, distinguish operational errors from uncertainty, and prove every terminal path leaves a trace. Use a fake inference adapter with fixed transcripts to cover ready, missing evidence, ambiguity, malformed responses, invalid citations, repeats, timeouts, unavailable capabilities, large diffs, and persistence failures. Test result-to-exit mapping and exact offline protocol replay. These tests verify mechanisms, not policy correctness.

Use Git fixtures for diverged target/source, detached heads, shallow missing history, fork refs, rebases, deletion-only changes, binary/large files, odd filenames, dirty working trees, submodules, renamed files, and zero/multiple merge bases. Verify source snapshot and control revision cannot be confused. Candidate instructions embedded in code/docs/provider suggestions must not escape the request vocabulary or override the policy.

Validate YAML-folder discovery, empty folders, duplicate IDs/keys, aliases/custom tags, document roots, and raw/normalized pack hashes. Exercise lossless chunk reconstruction, cap enforcement including oversized lines/metadata, every-unit scheduling, insufficient run budgets, cross-chunk violations, required reconciliation, duplicates/conflicts, and chunk-size/order sensitivity.

Use native Jev choice/noul response fixtures. Check category probabilities separately from provider confidence, candidate ID whitelisting, missing candidates, support selection, template-origin feedback, model-routing identity, 503 retry limits, and token/cost metadata. Ensure no test expects generated prose or arbitrary request JSON from Jev. Live Gateway checks are a later explicit implementation-validation step and have not run.

## Layer 2: provider feasibility

Run the [provider fixture gate](evidence-providers.md) before committing to Ripwire capabilities. Check Java definitions, ambiguous calls, interface implementations, test associations, and dependency relations. No index result is treated as complete unless its declared scope supports that claim. Test precision, coverage, truncation, unavailable/malformed evidence, cache invalidation, and cold/warm cost. Add an existing precision provider or mark an operation unsupported when needed; do not build parsers.

## Layer 3: human-labelled policy corpus

After the application foundation and constitution exist, refine roughly 5–8 nonredundant questions. Include clear violations/compliance, legitimate exceptions, minimal-context successes, context-dependent answers, genuine ambiguity, distractors, unsupported evidence, and bypass attempts. Humans label expected outcome, rationale, required evidence, acceptable uncertainty, and legitimate exceptions before seeing Jev's response. Preserve disagreements; a second independent human review/adjudication is desirable where available. Disclose single-reviewer limitations if not.

Separate development cases for prompt/retrieval tuning, calibration cases for threshold selection, and sealed held-out cases for acceptance. Split related variants/families together to avoid near-duplicate leakage. If a held-out suite becomes tuning data, create a new held-out version and disclose the change.

Compare minimal, adaptive, and bounded fixed-context strategies on paired cases under identical judge settings. Measure whether decisive requests are present in the candidate menu, whether Jev selects them, whether selected excerpts support the claim, whether requests are relevant, whether retrieved facts correct or corrupt a decision, whether unnecessary context hurts, confidence versus correctness, selective coverage, and limits. Report every policy separately; do not pool away a failing policy.

## Layer 4: repair behavior and deterministic CI

Use Qwen to repair preserved corpus violations from bounded, policy-authored feedback and selected evidence. Measure whether templates and chunk-level localization are sufficiently actionable without a separate generative explanation model. Audit genuine fixes, regressions, test weakening, policy changes, suppression, and retries. Green CI is only one observation. Exercise deterministic controls with independently constructed faults and legitimate changes; verify that baseline tests and hidden audits do not leak treatment feedback.

## Readiness decisions

Before unsealing held-out outcomes, record per-policy acceptable false-alarm/miss burden, minimum useful coverage, ambiguity handling, repair correctness, maximum runtime/context cost, and the evidence needed to judge them. Set corpus/sample sizes and uncertainty reporting with those targets. No unsupported numerical claims are supplied now.

Mechanism readiness requires complete traces for completed runs, successful replay, observed budget enforcement, reliable error handling, and no known silent missing-evidence path in supported operations. Policy readiness additionally requires satisfactory held-out performance under registered criteria. A policy can be removed for documented failure; include its failure in results. If no useful set survives, report that outcome and do not proceed merely because the end-to-end demo runs.

Only then finalize the realistic baseline and deterministic controls, freeze the 30-story campaign and all settings, and begin formal runs. Any material subsequent provider/model/policy/prompt/budget change requires new validation and an explicit experimental deviation.
