# Replayable Evidence Pack

Status: design revision 0.2, `jev.pack/0.2`. Every attempted run, including preflight failure, creates an inspectable pack when the output destination is writable. If even a minimal pack cannot be created, emit an operational error with an explicit trace-unavailable diagnostic; never claim that a pack exists. A run contains per-chunk/reconciliation evaluations and per-policy aggregates with separate IDs.

## Layout

```text
pack/
  manifest.json
  events.jsonl
  blobs/sha256/<digest>
  chunks/manifest.json
  policies/manifest.json
  evaluations/<evaluation-id>/result.json
  policies/<policy-id>/aggregate.json
  feedback.json
  summary.json
  checksums.json
```

`manifest.json` contains schema/run IDs, creation time, tool/build identity, repository and source/target/base identities, comparison metadata, control/policy/document/config hashes, model/inference/tokenizer settings, provider/index versions and licenses, environment reference, effective budgets, policy-folder manifest/hash, chunk strategy/config/manifest/hash, ordered work units, and required reconciliation. Record the policy repository revision when supplied. Paths are logical repository-relative paths, not machine-specific identities. Preserve original ref names as annotations.

`events.jsonl` is append-only. Each event has `schema_version`, monotonically increasing `sequence`, `run_id`, optional `evaluation_id`, UTC time, monotonic elapsed time, event type, optional policy/chunk/unit-kind fields, and a typed payload or content-addressed payload reference. Write in coordinator order even if future retrieval is concurrent. Hash immutable payload bytes with SHA-256. Record content encoding and byte length.

Also record `chunks_created`, `candidate_menu_built`, `request_selected`, `support_selected`, `unit_skipped`, `reconciliation_started`, and `policy_aggregated`, including omissions and conflicts. Required base event types: `run_started`, `comparison_resolved`, `scope_resolved`, `initial_evidence`, `prompt_sent`, `model_response`, `response_validated`/`response_rejected`, `evidence_requested`, `evidence_returned`, `budget_updated`, `decision_proposed`, `evaluation_finished`, `ci_action`, `run_finished`; plus explicit provider/inference/trace error and retry events. Every request and response has a correlation ID. Include elapsed cost for indexing/cache preparation, not only queries.

## What is preserved

Store exact policy/document/protocol text and effective configuration; raw diff/inventory and relevant Git objects or a reference to an exported Git bundle; exact initial and subsequently returned evidence; raw model response and validated response; request arguments; raw provider stdout/stderr and normalized items; exact serialized state/questions/criteria; all concrete candidate menus and their selections; native confidence and category probabilities; authored feedback template identity; all limits/counters; final outcome/action; token usage with origin (measured/estimated/unavailable); timing; and previous-attempt lineage when the caller supplies it.

The pack contains the delivered evidence bytes, not only file locations or hashes. Required repository/index artifacts have content hashes and export instructions. A thin pack without referenced blobs/bundles is marked incomplete and cannot claim self-contained replay. A source snapshot may be reconstructed from archived Git objects; language indexes can be rebuilt only if the build environment and inputs are pinned, otherwise include the index artifact.

Provider/model output exceeding a hard transport cap is terminated and recorded as an operational error with `raw_output_incomplete`, retained prefix hash, and cap details. Do not claim a complete response was preserved when it was not received. Credentials and secret environment values are never recorded; synthetic research data should make source redaction unnecessary. Any necessary redaction is explicitly recorded and limits replay claims.

## Replay modes

1. **Protocol replay:** reuse recorded model/provider responses and exact payloads, rerun schema/state/budget/CI mapping, and verify hashes. No inference, retrieval, or network. Identical protocol versions should produce identical logical results; wall-clock times are historical inputs.
2. **Retrieval verification:** rerun a pinned provider on the same snapshots/config and compare raw/normalized evidence. Separate nondeterminism, cache effects, and version changes from policy outcomes.
3. **Fresh evaluation:** rerun inference over the recorded initial state or recorded evidence sequence. Assign a new run ID and parent reference. This is a new observation, not deterministic replay.

## Durability and integrity

Write and flush each transition before its side effect where possible, and record completion afterward; an interrupted call remains explicitly incomplete. Write result/summary files atomically. Final checksums cover manifest, events, results, and blobs, excluding the checksum file itself. A clean finish event and matching checksums distinguish a sealed pack from an incomplete run. Hashes detect changes relative to a retained manifest; they do not prove authenticity if the whole archive is replaced. Use immutable artifact retention for formal runs.

If trace persistence fails, stop and return the operational-error exit status. CI must never report successful evaluation without a durable result/trace. Keep partial artifacts and an emergency stderr diagnostic; do not manufacture an empty success pack. Research exports include failures and abstentions alongside successful decisions.
