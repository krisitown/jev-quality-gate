# jev-ci command-line tool

Status: design revision 0.2. The four commands are implemented in the first Python package; see [implementation status](../implementation-status.md) for tested behavior and gaps.

## Commands and normal pipeline invocation

```sh
jev-ci validate --config /trusted/jev-ci.json --policies /trusted/policy-repo/policies

jev-ci evaluate \
  --repo /workspace/application \
  --source feature-branch \
  --target main \
  --policies /trusted/policy-repo/policies \
  --config /trusted/jev-ci.json \
  --output /artifacts/jev-run

jev-ci inspect --pack /artifacts/jev-run
jev-ci replay --pack /artifacts/jev-run --mode protocol
```

`--repo` is an existing local Git checkout; source may be a branch or commit. Local defaults are HEAD and `refs/heads/main`. CI fetches the actual source and trusted target and passes their commit IDs; it also checks out a chosen policy repository revision. `--policies` points to that folder, whether it is in the application repo, another repo, or a prepared artifact. Core does not clone URLs, fetch branches, or create remote repositories.

`validate` parses configuration and all YAML policies, validates references and budgets, and produces a pack identity/diagnostic report without inference. It validates policy structure; it does not establish policy usefulness or calibration. An empty policy folder or duplicate ID is an error, never successful evaluation of zero policies.

`evaluate` repeats structural validation, freezes inputs, prepares the diff manifest, schedules every applicable policy/chunk unit and required reconciliation, records evidence, and maps final outcomes to CI actions. It returns only after outputs are durably written, subject to explicit incomplete/error handling. User-supplied YAML is configuration and cannot grant unrestricted filesystem/tool access. Jev selects typed options; findings combine selected source excerpts with policy-authored feedback.

`inspect` renders stored findings, evidence references, coverage, costs, and incomplete units without calling the model. `replay --mode protocol` verifies recorded transitions and aggregation using saved responses; fresh inference is a separate, explicitly identified new evaluation and is not part of v0 replay.

## Configuration and folder semantics

`--config` supplies trusted root settings including Gateway connection, providers, document bindings, budgets, and CI actions. `--policies` supplies YAML definitions; neither silently loads from candidate HEAD. Resolve relative paths from the declaring config/policy file under its permitted root, not from an arbitrary current directory. Validate every file before inference. Hash raw files and their normalized representation, retaining relative paths and the externally supplied policy-repository commit when available.

For local development, explicit inputs establish the evaluated configuration and are recorded. Protected CI supplies the paths and expected hashes/revisions from trusted pipeline configuration. A candidate cannot use its own changes to override those inputs. Public example policies live in `jev-ci/examples/policies/`; the experiment will pin the same files/revision it publishes after refinement.

For local credential use, `--env-file <trusted-file>` explicitly loads only configured secret variables using a dotenv parser, with existing environment values taking precedence. It never shell-sources a file or automatically loads candidate-repository dotenv files. `validate` does not contact the Gateway or require the key to be live.

## Outputs and errors

Human progress and diagnostics go to stderr. Default stdout is one concise final summary; `--format json` produces a versioned JSON result on stdout, including error results where possible. Model/provider output never goes directly to a terminal; stored diagnostics exclude authorization headers and secret values. Artifact paths are included in the summary.

A run writes `summary.json`, `feedback.json`, the chunk/policy manifests, unit and aggregate results, and the replayable Evidence Pack. Feedback includes policy, bounded claim, source anchors, supporting evidence IDs, and repair guidance; uncertainty describes the missing evidence or ambiguity. The research harness controls coding-agent repairs.

Exit codes: 0 means no configured blocking action; 1 means a configured policy action blocked; 2 means an execution/configuration error. Report-only uncertainty can coexist with exit 0 but stays visible in coverage/status. `validate` and `inspect` use 0 for success and 2 for errors. A protocol replay that finds a mismatch exits 2. External cancellation preserves partial events where possible and uses conventional interruption status; it never seals a successful pack.

`--output` must be a new directory; reject overwrite by default. Concurrent runs have distinct IDs/output directories. v0 does not resume partial inference automatically; reruns receive new IDs and can reference earlier packs. Shared evidence caches are keyed by immutable inputs.

## Scope of the first implementation

The first implementation provides `validate`, `evaluate`, `inspect`, and protocol `replay` over a sequential coordinator and one Gateway adapter. Exact file/search retrieval and fixture-validated Ripwire callers/callees are present. The container wrapper and further provider capabilities remain future work.

## HTML report export (0.5)

New evaluations write checksummed `report.html` automatically. `jev-ci report --pack <saved-pack> --output <review.html>` creates an offline view using saved summary, chunk manifests and unit results. The output must stay outside the sealed pack to preserve its integrity. `--format json` reports the export path/status; the generated artifact is always HTML. No inference or source retrieval occurs. See [HTML reporting](html-reporting.md).
