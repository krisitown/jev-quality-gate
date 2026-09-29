# Evidence providers and open-source tooling

Status: design revision 0.2. Ripwire 0.6.5 is pinned by binary digest and exercised by executable Java fixtures plus caller/callee queries on a public Go PR. Graph completeness and recall remain unmeasured; see [implementation status](../implementation-status.md).

## Selection

Propose Ripwire as the first replaceable retrieval backend. Its [README](https://github.com/redhat-et/ripwire) documents Java support, symbol/call navigation, limited JSON command support, and heuristic resolution. Its [license](https://github.com/redhat-et/ripwire/blob/main/LICENSE) is Apache-2.0. Use it for evidence, not its architectural verdicts. Ripwire's ranking confidence is not Jev's judgment confidence.

The [upstream limits inventory](https://github.com/redhat-et/ripwire/blob/main/docs/LIMITS.md) describes both indexing and output caps, including cases without disclosure. Consequently, Jev cannot assume a complete graph simply because a query emitted no warning. Our adapter must declare known blind spots and validate the exact operations used against fixtures. Retain raw warnings and normalization details.

| Option | Use in this design | Tradeoff |
| --- | --- | --- |
| Ripwire | First candidate for broad structural retrieval | Low integration burden; precision/coverage must be measured |
| [scip-java](https://github.com/scip-code/scip-java) | Optional precomputed compiler-derived Java/Kotlin index | Apache-2.0; build/index cost and snapshot provenance must be handled |
| [Eclipse JDT LS](https://github.com/eclipse-jdtls/eclipse.jdt.ls) | Optional precise Java navigation via an existing LSP client | EPL-2.0; documents call/type hierarchy and Maven/Gradle support, but adds runtime/project-import management |
| Git objects + fixed-string search | Universal file/document/diff/search fallback | No semantic resolution; misses cannot prove absence |

SCIP supplies indexed symbol relationships, not a promise of every runtime call edge. JDT LS similarly cannot establish all Spring runtime wiring. Do not introduce either solely to enlarge the stack. We will not write tree-sitter grammars, custom Java parsers, regex-based semantic resolvers, or new language front ends.

## Adapter interface

`describe() -> ProviderDescriptor`: provider ID/version/binary digest, adapter version, license/provenance, supported request types per language, output schema version, precision classes, limitations, snapshot/index identity, and resource requirements.

`prepare(snapshot, trusted_config, budget) -> IndexDescriptor`: optional deterministic index, generated only from that snapshot. Record build inputs/toolchain for compiler-derived indexes. No hidden network fetch or build execution.

`retrieve(request, snapshot, budget) -> EvidenceResponse`: one authorized operation. Provider selection and fallback order are frozen configuration, never opportunistic upgrades during a run. No automatic package installation.

A response includes request ID, status, items, provider/index identity, elapsed time, returned bytes/tokens, truncation/skipped counts, warnings, and raw-output reference. Status is `ok`, `partial`, `not_found`, `ambiguous`, `unsupported`, `denied`, `timeout`, or `error`. `ok` means successful execution, not exhaustive semantic completeness.

Each item has framework evidence ID, snapshot commit (or immutable control-document identity), repository-relative path, blob/content hash, line/byte range or derived relationship, content/hash, relation kind when relevant, precision (`source_exact`, `syntax_derived`, `compiler_resolved`, `heuristic`), and coverage (`complete_for_declared_scope`, `partial`, `unknown`). Preserve edge provenance and candidate ambiguity. A relationship includes source locations supporting it. Framework IDs are stable within a pack; upstream symbol IDs are namespaced by snapshot/provider/index and cannot be reused across versions silently.

## Constrained vocabulary

All requests contain `id`, `type`, typed target, and concise `purpose`. Source requests additionally select `snapshot` (head/base/target), default head. A trusted `GET_DOCUMENT` uses only its binding ID and optional section: the binding determines its immutable control revision/content hash, so candidate snapshot selection cannot override it. Non-authoritative document requests use an explicitly permitted source snapshot/path. The framework clamps permitted output/hop limits to configuration. Paths must be relative and inside the authorized snapshot; reject traversal, absolute paths, shell fragments, and arbitrary provider flags.

| Request | Target / meaning |
| --- | --- |
| `GET_DIFF_CHUNK` | Chunk ID from the frozen manifest; supplied by the central chunking module with original ranges/caps |
| `GET_SYMBOL` | Evidence symbol ID, or path + qualified name/signature; definition/body with exact source range; ambiguous selectors return candidates |
| `GET_FILE` | Path and optional inclusive line range; exact committed text |
| `GET_CALLERS` | Symbol reference; incoming call candidates and declared resolution quality |
| `GET_CALLEES` | Symbol reference; outgoing call candidates and declared resolution quality |
| `GET_IMPLEMENTATIONS` | Interface/abstract symbol; known implementations, with incomplete dispatch/wiring disclosed |
| `GET_TESTS` | Symbol or path; candidate related tests with linkage basis; does not run them |
| `GET_DEPENDENCY_NEIGHBORHOOD` | Symbol/path, direction, max hops (default 1, hard ceiling 2); typed import/reference/call edges, never conflated |
| `SEARCH_CODE` | Bounded literal query and allowed path scope; fixed-string search in v0, no arbitrary regex or shell |
| `GET_DOCUMENT` | Trusted document binding ID, optional section; or explicitly permitted non-authoritative snapshot document |

Provider verbs are mapped to these operations. The controller constructs concrete request candidates and Jev selects a bounded choice ID; native Jev does not generate arbitrary tool arguments. `GET_DIFF_CHUNK` uses a manifest ID, not a caller-selected snapshot. Other source/document request semantics remain as above. Initially use Ripwire expansion and callers/callees where verified; use Git for exact file contents and literal search. Implementations/test associations/dependency neighborhoods are conditional capabilities: advertise only after fixture verification, otherwise return unsupported. A compiler index or LSP adapter can supply missing capabilities later.

For output integration, use supported JSON modes and a standard XML parser elsewhere; never scrape terminal prose as structured facts. The [command reference](https://github.com/redhat-et/ripwire/blob/main/docs/COMMANDS.md) is a discovery source, while the pinned binary's output fixtures define our adapter compatibility. Ignore any suggested follow-up command except as non-executable data. Strip neither incompleteness markers nor warnings.

## Feasibility gate, before adoption

Use small committed fixtures with overloads, interfaces, inheritance, duplicate names, multiple modules, generated code, and Spring-style indirection. Compare retrieved definitions/relationships against manually checked answers. Include exact snapshot replay, malformed output, missing index, unknown language, truncation, and stale-cache cases. A failed capability stays unsupported or uses a validated existing tool; it does not trigger building a custom parser. Preserve failures in the provider report.
