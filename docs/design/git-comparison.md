# Git branch comparison and trust

Status: design revision 0.2. Default mode: source-branch change since divergence from a protected target.

## Inputs and descriptor

Required: repository path and source ref/commit (CLI default `HEAD`). Target branch defaults to `main`; local default resolves specifically `refs/heads/main`. CI should supply the target commit explicitly after fetching from its trusted remote. Never silently choose `origin/main`, a same-named fork ref, or a platform-generated merge commit.

Resolve once into `source_commit`, `target_commit`, and `comparison_base = merge-base(target_commit, source_commit)`, retaining original ref strings, object format, tree IDs, repository identity, diff options, and hashes. Compare `comparison_base` to `source_commit`. Target advancement therefore does not appear as source-authored deletions. This follows [Git's three-dot comparison](https://git-scm.com/docs/git-diff). All later reads use immutable object IDs.

The control bundle has a separate pinned identity, normally a target-revision artifact or trusted external configuration. It need not be the historical merge base. Candidate changes to rules/config/docs are proposed changes and cannot grant themselves exceptions. Authoritative policy documentation comes from declared control-bundle bindings. Candidate documents can be non-authoritative evidence.

## Algorithm

1. Validate repository, commit identities, trusted target/control inputs, and available objects. Report dirty state but evaluate committed objects only; uncommitted edits are excluded.
2. Compute all best merge bases. Zero or multiple bases are unsupported in v0 and produce an operational error. Never select arbitrarily; [Git documents multiple possible bases](https://git-scm.com/docs/git-merge-base).
3. Generate a complete NUL-safe path inventory with fixed options: no external diff/textconv/color, Myers algorithm, three context lines, no rename detection in v0. Renames appear as deletion/addition; preserve blob IDs for audited issue matching.
4. Store the raw diff and path/blob metadata within declared ingestion limits. Pass it to the single [diff chunking module](diff-chunking.md), then schedule every applicable policy/chunk pair. Initial state contains one bounded chunk, pertinent trusted conventions, and cheap changed-symbol metadata.
5. Retrieve from `base`, `head`, or `target` snapshots, always labelled with actual commit. `base` is the comparison base; `target` is the protected tip. Default request snapshot is `head`.

Core never implicitly fetches. A runner may fetch/deepen explicitly and invoke a new run. Missing shallow history, refs, or fork objects are operational errors. Detached HEAD is supported when it is the actual source commit. Wrappers must distinguish source-head from synthetic merge-result jobs; merge-result analysis is deferred.

## Scope and exceptional content

Inventory remains complete even if content cannot be evaluated. Binary files, missing LFS objects, undecodable text, submodules, oversized files, and symlinks have explicit coverage status. v0 neither recurses into submodules nor downloads LFS objects. Relevant unsupported content makes the affected policy uncertain. A declared scope with no changed paths is `not_applicable`, not compliant.

Large changes are processed as bounded chunks, not one complete prompt. Chunk creation preserves all textual change ranges; total ingestion/run limits are separate and reported explicitly. Unvisited chunks prevent a compliant aggregate. Cross-chunk reconciliation and chunk-size sensitivity must be validated before the cumulative campaign is frozen.

Findings cite introduced/worsened changes or a change-linked semantic impact. Existing unchanged issues remain pre-existing context. An omission introduced by deletion may cite base-side evidence and the deletion hunk.

## Portable integration

GitHub, GitLab, another runner, and local use share resolved inputs and output semantics. Wrappers own trusted checkout/fetch, source and target identity, protected configuration, secrets, and retention. Branch protection is enforced externally; Git cannot prove it. Stacked branches include all changes relative to the configured target. If target advances mid-run, finish against the pinned SHA and rerun before merge when the platform requires it.
