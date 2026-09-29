# Milestone 1 design review — revision 0.2

Status: revision 0.2 design, dated 2026-09-28. The first implementation was added 2026-09-29; see [implementation status](../implementation-status.md) for exercised features and remaining gaps. This design has not been frozen for the research campaign.

## The tool

`jev-ci` is a portable CI command. Supply a repository checkout, source branch/commit, protected target (main by default), a folder of YAML policies, and trusted runtime settings. It pins inputs, splits the diff into bounded chunks, evaluates all applicable policy/chunk units with TypeSafe Jev through Vercel AI Gateway, gathers extra evidence from a constrained candidate menu, reconciles cross-chunk judgments, and saves results plus replayable evidence. CI decides which outcomes block.

## Reading order

| Document | Review focus |
| --- | --- |
| [CLI design](cli-design.md) | validate/evaluate/inspect/replay, inputs, outputs, invocation |
| [Gateway integration](gateway-integration.md) | Actual Jev route, typed answers, credentials, retries, telemetry |
| [Diff chunking](diff-chunking.md) | One replaceable module, hard limits, traversal, aggregation |
| [YAML policies](policy-schema.md) | External policy folders, bounded questions, authored feedback |
| [Architecture](architecture.md) | Components and separation of responsibilities |
| [Git comparison](git-comparison.md) | Pinned source/target/base and trusted control revision |
| [Evaluation protocol](evaluation-protocol.md) | Typed choices, candidate requests, abstention, confidence |
| [Evidence providers](evidence-providers.md) | Ripwire/other open-source adapters and declared limitations |
| [Evidence Pack](evidence-pack.md) | Durable trace, chunk/candidate manifests, replay |
| [Configuration and CI](configuration-ci.md) | Root settings, limits, exit codes, feedback |
| [Validation plan](validation-plan.md) | Future mechanism/provider/policy/repair validation |

## Decisions incorporated

The first inference adapter uses the same native Vercel Gateway endpoint and `typesafe-ai/jev` model as the user's existing projects. Jev answers predefined typed questions; earlier prose assuming generated request JSON or explanations was incorrect and is superseded. Our controller owns adaptive state transitions, request construction, templates, and CI mapping. Qwen generates and repairs experiment code.

A single `diff_chunking.py` module partitions by size without language semantics. All applicable chunks are scheduled and omissions stay explicit. Per-policy reconciliation guards against interactions missed by isolated chunks. Policies are `.yaml`/`.yml` files under `--policies`; the public experiment examples will live in `examples/policies/` and be pinned by revision/hash.

Python 3.12+ remains the proposed implementation language; direct bounded HTTP avoids requiring a JavaScript AI SDK. Ripwire is a replaceable retrieval candidate, subject to fixture validation. Existing open-source tools provide syntax/semantic navigation; there are no custom language parsers or additional generative discovery model in v0.

## Remaining empirical choices

Validate Gateway response/usage/limits and whether an exact tokenizer or conservative token bound is available. Validate the candidate menu and Ripwire capabilities, especially cross-file evidence. Refine the initial 5–8 policies and their architecture document bindings, measure whether template feedback enables correct repairs, then calibrate scores and chunk/run budgets. These tasks precede formal experiment freeze; no thresholds are invented here.

Current deliverable: a Python CLI, mechanism tests, demo configuration, and CI examples alongside these design documents. Mechanism tests use mocked responses and a verified Ripwire binary; live Gateway and three public-PR runs are documented in the [validation report](../validation/public-prs-2026-09-30.md). The tool is published at [krisitown/jev-quality-gate](https://github.com/krisitown/jev-quality-gate). Human-labelled policy calibration, the application-specific experiment policy pack, and the formal campaign remain later work.
