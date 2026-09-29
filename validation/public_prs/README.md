# Public PR validation harness

This harness reproduces three pinned, public pull request comparisons using the independent frozen controls in `controls/`. The cases cover Python, Go, and JavaScript/TypeScript at small, medium, and large change sizes. `cases.json` records each repository URL, PR head, stated base, expected unique merge base, language, license, size, and SHA-256 hashes for the control files.

The three policies are exploratory calibration controls. Their mode is `calibration` and every CI action is `report`; they cannot block a change. They are not human labels and their expected outcomes must not be presented as accuracy evidence.

The default operation fetches the pinned Git objects, checks out each exact head without running project code, verifies the expected merge base and license file, and writes provenance summaries. Use a new output directory outside this checkout:

```sh
python3 validation/public_prs/run.py --output /tmp/jev-public-prs-run
```

Preparation requires Git and network access to GitHub. Git hooks, global/system Git configuration, credential helpers, external diff drivers, and interactive prompts are disabled for these commands. Candidate build files, tests, setup scripts, and application code are never run.

Evaluation is opt-in and makes paid live Gateway requests. Install this project as `jev-ci`, then pass `--evaluate`; an API key already in the process environment is passed through to the CLI, or provide a dotenv file using `--env-file`. The harness does not open or print the credential file or key.

```sh
python3 validation/public_prs/run.py \
  --output /tmp/jev-public-prs-evaluated \
  --evaluate \
  --jev-ci .venv/bin/jev-ci \
  --env-file /path/to/jev-ci.env
```

Evaluation writes each Evidence Pack under `packs/`, captures the CLI evaluation summary under `evaluations/`, runs offline protocol replay, and writes JSON and Markdown reports under `reports/`. Packs and fetched source trees stay in the chosen output directory; do not commit that output directory.

The fixture tests use fake subprocess results and make no network or Gateway calls:

```sh
python3 -m pytest tests/test_public_pr_harness.py
```
