# Diff chunking and policy aggregation

Status: design revision 0.2. User-directed change: evaluate bounded pieces of the diff, with all partitioning logic in one replaceable module.

## One owner and a stable contract

The implemented `diff_chunking.py` module owns segmentation, cap enforcement, continuation metadata, coverage ranges, and chunk IDs. Its interface is `chunk_diff(change, limits) -> ChunkManifest` plus `read_chunk(chunk_id) -> DiffChunk`. The coordinator, inference adapter, and providers consume this contract; none may contain their own diff slicing, truncation, or chunk-size constants. Changing the strategy changes a version field and invalidates chunk-dependent caches, without changing consumers.

This module handles Git patch structure only. It does not parse programming languages or group by classes/functions. v0 partitions deterministically by size, preferring line boundaries; boundaries may fall inside files or hunks. A very long UTF-8 line may be split at code-point boundaries, with byte ranges and continuation markers. Preserve every raw diff byte exactly once in payload ranges; repeated identifying metadata is separate.

## Hard limits

Use a single root configuration section for all diff limits. Proposed development values (unvalidated) are:

```json
{
  "diff": {
    "strategy": "bounded-sequential-v1",
    "max_chunk_bytes": 12000,
    "max_total_diff_bytes": 8388608,
    "max_chunks": 1024
  }
}
```

`max_chunk_bytes` limits the complete serialized chunk envelope sent as diff evidence, including identifying metadata. The entire request also has its own model/context limit. Start each request with one primary chunk; every retrieved chunk obeys the same cap and counts toward evidence/prompt budgets. No request silently concatenates all chunks.

`max_total_diff_bytes` is a separate ingestion/storage limit on the raw patch. Count bytes while generating it. Exceeding it produces `uncertain: diff_limit_exceeded` with a marked partial artifact and full path inventory where available; do not evaluate a truncated prefix as the branch. Likewise report `chunk_count_exceeded` or `chunk_metadata_too_large` explicitly. The normal size cap creates more chunks; it does not discard the remainder. These prototype values must be checked against cumulative story-30 changes before freeze.

## Chunk manifest

Record strategy/version, diff hash, comparison commits, configured caps, total raw bytes, ordered chunk IDs, and status for unsupported content. Each chunk carries ordinal, content hash, raw byte ranges, affected paths, old/new blob IDs, hunk/source coordinates, and continuation links. Its ID hashes change identity, strategy/config, ranges, and payload. Raw-range concatenation reconstructs the textual diff; readers never rely on a fragment being a standalone applicable patch.

Create a complete manifest before inference. Path filtering selects each policy's chunk intersections deterministically. A chunk with changes to multiple files cannot hide relevant content because another path is excluded. Record scheduled/skipped units and reasons. `not_applicable` means no change falls within declared policy scope, not that a model guessed it irrelevant.

## Evaluation schedule and cross-chunk evidence

A work unit is `(policy_id, chunk_id)`. Iterate chunk ordinals, then stable policy IDs, using independent adaptive sessions. Every applicable unit is scheduled; one violation does not end traversal. Reserve minimum calls/input/output allowance for remaining initial units and required reconciliation before granting extra evidence rounds. If configured run caps cannot accommodate even that minimum, emit explicit uncertainty before inference. Runtime timeouts can still interrupt work; list every unfinished unit.

The initial unit state contains policy, bound conventions, one chunk, cheap local symbol metadata, and a bounded index of related changed paths/chunks. It carries totals and omissions if the index itself is capped. `GET_DIFF_CHUNK` retrieves any authorized chunk from the frozen manifest, including another file; normal symbol/file/search requests can inspect base and head across the repository. A clipped file/hunk is not a complete function. Record supplied ranges and unresolved cross-chunk relationships.

## Aggregation

Each policy declares `aggregation.mode`: `requires_reconciliation` (default), or `independent_chunks` only when human review establishes that violations cannot depend on interactions between units. The latter is a strong policy assumption that must be tested with counterexamples.

For reconciliation, run one additional bounded adaptive evaluation per policy using a compact index of unit statuses, evidence-backed findings, and open questions. This is a separate work unit; it can retrieve original chunks and source facts through the same Context Engine. Prior typed verdicts and template summaries are claims, never ground truth; Jev does not generate narrative summaries. If the index or decisive evidence cannot fit, reconciliation is uncertain; do not truncate silently or repeatedly summarize away the limit. A policy without a defensible branch-level evaluation scope should abstain rather than imply complete assurance.

The deterministic aggregator reports:

- **Violation** when at least one supported, accepted finding remains. Continue evaluating other units and retain unresolved gaps. A later contrary assertion cannot silently erase a finding; record the conflict and resolve it with cited source evidence within budget, otherwise mark the disputed claim uncertain.
- **Compliant** only when every applicable unit is completed/compliant, there are no known decisive gaps or unresolved findings, and required reconciliation is compliant. This remains a bounded probabilistic judgment, not proof of absence.
- **Uncertain** when no accepted violation remains but a unit/reconciliation is uncertain, unvisited, disputed, or unable to establish coverage.
- **Error** as execution health when a systemic/provider/model protocol failure occurs. Retain completed judgments, but CI error takes precedence.

Do not average confidence scores. Preserve confidence per proposal/unit and reconciliation; aggregate confidence is null. Apply thresholds before accepting unit findings. Deduplicate only exact normalized matches of policy, claim, and source anchors; retain links to every contributing unit and leave semantic near-duplicate matching to audited analysis. Multiple chunks reporting the same issue must not inflate experiment counts.

Required validation includes a business rule split over two chunks, duplicate policy implementations in different files, different chunk sizes/order, oversized single lines, capped manifests, incomplete runs, conflicting findings, and exact raw-range reconstruction. Freeze chunking strategy and parameters alongside policies for the formal experiment.
