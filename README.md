# Jev CI

Jev CI evaluates **committed source-branch changes** against a protected target with bounded YAML policies. It resolves both refs to commits, compares the source to their merge base, divides the complete patch into capped chunks, asks [TypeSafe Jev](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe) typed questions through Vercel AI Gateway, and writes an inspectable Evidence Pack. It never builds or executes candidate code.

Version0.3 implements [verdict-first evidence acquisition](docs/design/evaluation-protocol.md), with a live Gateway integration and real-world engineering validation on public Flask, Gin, and Svelte pull requests. See the [validation report](docs/validation/public-prs-2026-09-30.md) for exact commits, policies, outcomes, cost, and limitations. The included policies are **report-only and uncalibrated**; human-labelled accuracy validation and the separate 30-story experiment remain future work.

## Install

Python 3.12 or newer and Git are required. The CLI is tested on macOS and Linux. Clone the repository and install it in a virtual environment:

```sh
git clone https://github.com/krisitown/jev-quality-gate.git
cd jev-quality-gate
python -m venv .venv
.venv/bin/python -m pip install -e . -c constraints.txt
.venv/bin/jev-ci validate --config examples/demo/config.json
```

The last command checks the included demo config and policy without making a Gateway request. Run `.venv/bin/jev-ci --help` for every command and option. The demo policy is illustrative and must be adapted to your project's architecture before its results are useful.

## Run on a branch

Put your own `config.json`, policy YAML files, and hash-bound documents in `.jev-ci/` on your application's protected branch. [The demo control bundle](examples/demo/config.json) shows the required layout and fields. Keep the config and policy folder together so its relative `policy_dir` and document paths resolve correctly. The evaluator reads committed source changes against the merge base with the target branch; dirty working-tree edits are excluded.

From the installed tool directory, fetch the target and create a separate checkout for trusted controls. This example assumes the application has a local `feature` branch and a remote `main` branch:

```sh
git -C /path/to/application fetch origin main
git -C /path/to/application worktree add --detach /tmp/jev-controls origin/main
cp .env.example .env.local
chmod 600 .env.local
# Put your AI_GATEWAY_API_KEY value in .env.local.
.venv/bin/jev-ci validate --config /tmp/jev-controls/.jev-ci/config.json
.venv/bin/jev-ci evaluate \
  --repo /path/to/application \
  --source feature \
  --target origin/main \
  --config /tmp/jev-controls/.jev-ci/config.json \
  --output /tmp/jev-pack \
  --env-file .env.local
.venv/bin/jev-ci inspect --pack /tmp/jev-pack --format json
.venv/bin/jev-ci replay --pack /tmp/jev-pack --mode protocol
```

Use a new `--output` path for each run. `--source` defaults to `HEAD`; `--target` defaults to the local `refs/heads/main`. The tool itself never fetches, so ensure both refs exist locally. For reproducible CI runs, pass commit IDs instead of moving branch names. Exit codes are 0 for an allowed result, 1 for a configured block, and 2 for an operational error. `--format json` gives a versioned machine-readable summary. Each pack also contains `report.md` with policy outcomes, source anchors for findings, uncertainty diagnostics, and reported usage/cost. Feedback text is authored by the policy, and missing evidence remains visible even when the CI action allows the run.

The [GitHub Actions example](examples/github/jev-ci.yml) checks out the target history, explicitly fetches the pull request head (including a fork's head ref), and checks out protected controls and a pinned tool revision separately. Copy it into your application's `.github/workflows/`, replace `PINNED_TOOL_COMMIT_SHA` with a reviewed commit from this repository, and create an `AI_GATEWAY_API_KEY` repository secret. It uploads the Evidence Pack even when evaluation fails. GitHub does not expose repository secrets to `pull_request` workflows triggered by forks, so those runs need an approved credential strategy before they can call the Gateway. The package's own [CI job](.github/workflows/ci.yml) runs lint, unit tests, and the pinned Ripwire fixture.

## Trust and limits

Root configuration is JSON; policies are YAML files discovered recursively under the supplied folder. Documents are bound to hashes in the trusted control directory. The CLI never reads policy settings from the candidate branch by default. Root settings own loop count and serialized input size; policies can narrow retrieval-size limits and cannot select arbitrary commands or file paths. Its `scope` selects changed files; its authored terms and permitted requests shape a bounded request menu. Jev chooses menu IDs and support IDs; the controller executes only its own validated requests. Feedback prose comes from policy templates and is labelled accordingly.

The initial provider supports exact committed file, literal search, diff chunk, and trusted document evidence. Ripwire 0.6.5 is optional: when enabled with a pinned binary SHA-256, it indexes a temporary snapshot materialized directly from the **source commit's blobs** and offers JSON callers/callees queries. Its graph results are labelled heuristic and partial, including upstream ambiguity and floor counts. Snapshot materialization and exact searches read committed blobs in batches, with byte caps and a shared run deadline; skipped files and bounded search excerpts are disclosed. Other semantic verbs remain unsupported until fixture validation. [Provider details](docs/design/evidence-providers.md) explain the limits.

To enable it, replace the demo config's `providers` section with a trusted binary path and its actual checksum:

```json
{
  "enabled": ["git-exact", "ripwire"],
  "ripwire": {
    "binary": "/trusted/bin/ripwire",
    "sha256": "<64-character-sha256>",
    "version": "0.6.5",
    "timeout_seconds": 15,
    "max_output_bytes": 50000,
    "max_snapshot_bytes": 33554432,
    "max_symbols": 200
  }
}
```

The diff module owns chunk size, byte ranges, reconstruction, and chunk IDs. It reports a whole-diff limit or chunk-count failure as incomplete; no clipped prefix is treated as complete. Every applicable chunk is scheduled, followed by required policy reconciliation. The pack retains frozen inputs, source evidence, typed responses, ordered events, results, feedback, and checksums. Protocol replay checks checksums, typed answers, ordered request/response/result links, unit diagnostics, deterministic aggregates, and CI mapping without network access. It does not re-execute every controller transition, retrieval operation, or model inference, and checksums alone cannot authenticate an archive that was wholly replaced. Aggregate confidence is intentionally null; unit scores remain available.

`AI_GATEWAY_API_KEY` comes from the process environment or an explicitly named dotenv file; the process environment wins. The key is never logged or stored in the pack. The Gateway adapter uses the native `typesafe-ai/jev` endpoint, bounded request/response bytes and deadline, and at most one retry on HTTP 503. The loop checks the complete serialized UTF-8 request against `limits.max_input_bytes` and the adapter byte cap before every call, including after a fetch. These are byte limits, not exact vendor-token limits; actual Gateway token usage and decimal USD cost are preserved when returned. `limits.max_rounds` controls follow-up count; the example config uses1,000,000. Unresolved answers always acquire the top remaining real request, while accepted compliant/supported-violation verdicts terminate immediately. The menu stays bounded and disclosed; omitted candidates alone do not veto compliance. Empty retrievals are recorded and skipped. See [v0.3 release notes](CHANGELOG.md) for migration details. Unknown or failed-call billing remains unknown. Routing metadata is retained and another evaluator identity is rejected. Provider and model aliases can still limit reproducibility, so record the exact tool, policy, and control revisions in a real study.

## Reproduce the public PR checks

The [validation harness](validation/public_prs/README.md) includes frozen public commit IDs, independent policies, and hash-bound conventions. Prepare the source without live calls, then optionally evaluate it using your Gateway key:

```sh
.venv/bin/python validation/public_prs/run.py --help
```

The report documents initial adverse outcomes and the final run; completing a run is distinct from proving policy accuracy.

## Development

```sh
python -m pip install -e '.[test]' -c constraints.txt
ruff check src tests
ruff format --check src tests
pytest -q
```

Set `JEV_CI_RIPWIRE_BIN` to a verified Ripwire 0.6.5 binary to run the executable provider fixtures. The self-hosted CI workflow downloads its pinned Linux release and checks the archive digest before those tests. Tests use temporary committed Git branches and a fake Gateway transport; they make no paid API calls.

The current implementation scope and validation gaps are tracked in [implementation status](docs/implementation-status.md). The research campaign remains gated by the [validation plan](docs/design/validation-plan.md). Licensed under [Apache-2.0](LICENSE).
