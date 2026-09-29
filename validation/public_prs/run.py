#!/usr/bin/env python3
"""Prepare pinned public PR snapshots; evaluation is an explicit opt-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jev_ci.config import load_config  # noqa: E402
from jev_ci.errors import JevCIError  # noqa: E402
from jev_ci.process import ProcessResult, run_bounded  # noqa: E402
from jev_ci.reporting import render_markdown  # noqa: E402

HARNESS_ROOT = Path(__file__).resolve().parent
CASES_PATH = HARNESS_ROOT / "cases.json"
CONTROL_FILES = ("config.json", "policy.yaml", "convention.md")
SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GIT_TIMEOUT_SECONDS = 600
OUTPUT_LIMIT = 1024 * 1024


def _safe_git_env() -> dict[str, str]:
    """Give Git only path, temp and TLS settings; never pass inference secrets."""
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "LANG": "C",
            "LC_ALL": "C",
        }
    )
    return env


def load_cases(path: Path = CASES_PATH) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "jev.public-pr-validation/1":
        raise ValueError("unsupported public PR case schema")
    cases = raw.get("cases")
    if not isinstance(cases, list) or len(cases) != 3:
        raise ValueError("expected the three frozen public PR cases")
    by_id = {}
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_RE.fullmatch(case_id):
            raise ValueError("invalid public PR case ID")
        if case_id in by_id:
            raise ValueError(f"duplicate public PR case: {case_id}")
        for field in ("head_commit", "base_commit", "expected_merge_base"):
            if not isinstance(case.get(field), str) or not SHA_RE.fullmatch(
                case[field]
            ):
                raise ValueError(f"{case_id}: invalid pinned {field}")
        repository = case.get("repository")
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError(f"{case_id}: invalid GitHub repository slug")
        if case.get("pull_request_url") != (
            f"https://github.com/{repository}/pull/{case.get('pull_request')}"
        ):
            raise ValueError(f"{case_id}: PR URL does not match repository metadata")
        if case.get("repository_url") != f"https://github.com/{repository}":
            raise ValueError(
                f"{case_id}: repository URL does not match repository slug"
            )
        by_id[case_id] = case
    return by_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def verify_controls(
    case: dict, controls_root: Path = HARNESS_ROOT / "controls"
) -> dict:
    """Check byte-for-byte frozen controls and their report-only calibration mode."""
    from jev_ci.policy import load_policies

    control_dir = controls_root / case["id"]
    expected = case["controls_sha256"]
    for name in CONTROL_FILES:
        path = control_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{case['id']}: missing regular frozen control {name}")
        if _sha256(path) != expected.get(name):
            raise ValueError(f"{case['id']}: frozen control hash mismatch: {name}")
    config = load_config(control_dir / "config.json")
    pack = load_policies(control_dir, config)
    if config.mode != "calibration":
        raise ValueError(f"{case['id']}: frozen controls must remain calibration-only")
    for policy in pack.policies:
        if set(policy.data["ci"].values()) - {"report", "warning"}:
            raise ValueError(f"{case['id']}: policy actions must remain report-only")
        if policy.data["ci"].get("compliant") != "report":
            raise ValueError(f"{case['id']}: compliant action must remain report-only")
        if policy.data["ci"].get("violation") != "report":
            raise ValueError(f"{case['id']}: violation action must remain report-only")
        if policy.data["ci"].get("uncertain") != "report":
            raise ValueError(
                f"{case['id']}: uncertainty action must remain report-only"
            )
    return {
        "config_sha256": expected["config.json"],
        "policy_sha256": expected["policy.yaml"],
        "convention_sha256": expected["convention.md"],
        "mode": config.mode,
        "policies": [policy.id for policy in pack.policies],
        "actions": "report-only",
    }


def _git_args(repo: Path | None, hook_dir: Path, *args: str) -> list[str]:
    command = [
        "git",
        "-c",
        f"core.hooksPath={hook_dir}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "credential.helper=",
        "-c",
        "diff.external=",
    ]
    if repo is not None:
        command.extend(("-C", str(repo)))
    command.extend(args)
    return command


def _run(
    command: list[str],
    *,
    runner: Callable[..., ProcessResult] = run_bounded,
    timeout: float = GIT_TIMEOUT_SECONDS,
    max_output: int = OUTPUT_LIMIT,
    env: dict[str, str] | None = None,
) -> bytes:
    result = runner(
        command,
        env=env if env is not None else _safe_git_env(),
        timeout_seconds=timeout,
        max_output_bytes=max_output,
    )
    if result.output_exceeded:
        raise RuntimeError(f"bounded command output exceeded for {command[0]}")
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace")[:300].strip()
        raise RuntimeError(f"command failed ({result.returncode}): {detail}")
    return result.stdout


def _git_text(
    repo: Path,
    hook_dir: Path,
    *args: str,
    runner: Callable[..., ProcessResult] = run_bounded,
) -> str:
    return (
        _run(_git_args(repo, hook_dir, *args), runner=runner, max_output=64 * 1024)
        .decode("ascii")
        .strip()
    )


def prepare_case(
    case: dict,
    output_root: Path,
    controls_root: Path = HARNESS_ROOT / "controls",
    *,
    runner: Callable[..., ProcessResult] = run_bounded,
) -> dict:
    provenance = verify_controls(case, controls_root)
    output_root.mkdir(parents=True, exist_ok=True)
    hook_dir = output_root / ".disabled-hooks"
    hook_dir.mkdir(exist_ok=True)
    repo = output_root / "repos" / case["id"]
    repo.parent.mkdir(parents=True, exist_ok=True)
    _run(_git_args(None, hook_dir, "init", "--quiet", str(repo)), runner=runner)
    _run(
        _git_args(
            repo,
            hook_dir,
            "remote",
            "add",
            "origin",
            case["repository_url"] + ".git",
        ),
        runner=runner,
    )
    _run(
        _git_args(
            repo,
            hook_dir,
            "fetch",
            "--quiet",
            "--no-tags",
            "--filter=blob:none",
            "origin",
            f"+{case['head_commit']}:refs/jev/head",
        ),
        runner=runner,
    )
    _run(
        _git_args(
            repo,
            hook_dir,
            "fetch",
            "--quiet",
            "--no-tags",
            "--filter=blob:none",
            "origin",
            case["base_commit"],
        ),
        runner=runner,
    )
    fetched_head = _git_text(
        repo, hook_dir, "rev-parse", "--verify", "refs/jev/head^{commit}", runner=runner
    )
    if fetched_head != case["head_commit"]:
        raise ValueError(f"{case['id']}: fetched PR head differs from pinned SHA")
    fetched_base = _git_text(
        repo,
        hook_dir,
        "rev-parse",
        "--verify",
        f"{case['base_commit']}^{{commit}}",
        runner=runner,
    )
    if fetched_base != case["base_commit"]:
        raise ValueError(f"{case['id']}: fetched base differs from pinned SHA")
    merge_bases = _git_text(
        repo,
        hook_dir,
        "merge-base",
        "--all",
        case["head_commit"],
        case["base_commit"],
        runner=runner,
    ).splitlines()
    if merge_bases != [case["expected_merge_base"]]:
        raise ValueError(
            f"{case['id']}: expected unique merge base {case['expected_merge_base']}, got {merge_bases}"
        )
    _run(
        _git_args(
            repo,
            hook_dir,
            "checkout",
            "--quiet",
            "--detach",
            case["head_commit"],
        ),
        runner=runner,
    )
    checkout = _git_text(repo, hook_dir, "rev-parse", "HEAD", runner=runner)
    if checkout != case["head_commit"]:
        raise ValueError(f"{case['id']}: checkout does not match pinned PR head")
    _git_text(
        repo,
        hook_dir,
        "cat-file",
        "-e",
        f"{case['head_commit']}:{case['license_file']}",
        runner=runner,
    )
    prepared = {
        "case": case["id"],
        "repository": case["repository"],
        "pull_request_url": case["pull_request_url"],
        "head_commit": checkout,
        "base_commit": case["base_commit"],
        "merge_base": merge_bases[0],
        "expected_merge_base": case["expected_merge_base"],
        "language": case["language"],
        "license_family": case["license_family"],
        "size": case["size"],
        "controls": provenance,
        "repository_path": str(repo),
        "candidate_code_executed": False,
    }
    (output_root / "prepared" / f"{case['id']}.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (output_root / "prepared" / f"{case['id']}.json").write_text(
        json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return prepared


def _tool_command(tool: str | None) -> list[str]:
    selected = tool or shutil.which("jev-ci")
    if not selected:
        raise ValueError("jev-ci is not installed; pass --jev-ci /path/to/jev-ci")
    return [selected]


def evaluate_case(
    case: dict,
    prepared: dict,
    output_root: Path,
    controls_root: Path,
    tool: list[str],
    env_file: Path | None,
    *,
    runner: Callable[..., ProcessResult] = run_bounded,
) -> dict:
    control_dir = controls_root / case["id"]
    pack = output_root / "packs" / case["id"]
    pack.parent.mkdir(parents=True, exist_ok=True)
    args = [
        *tool,
        "evaluate",
        "--repo",
        prepared["repository_path"],
        "--source",
        case["head_commit"],
        "--target",
        case["base_commit"],
        "--config",
        str(control_dir / "config.json"),
        "--policies",
        str(control_dir),
        "--output",
        str(pack),
        "--format",
        "json",
    ]
    if env_file is not None:
        args.extend(("--env-file", str(env_file.resolve())))
    result = _invoke_tool(runner, args, "evaluation", timeout=660)
    evaluation = _parse_tool_json(result, "evaluation")
    (output_root / "evaluations").mkdir(parents=True, exist_ok=True)
    (output_root / "evaluations" / f"{case['id']}.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    replay_result = _invoke_tool(
        runner,
        [
            *tool,
            "replay",
            "--pack",
            str(pack),
            "--mode",
            "protocol",
            "--format",
            "json",
        ],
        "replay",
        timeout=120,
    )
    replay = _parse_tool_json(replay_result, "replay")
    inspect_result = _invoke_tool(
        runner,
        [*tool, "inspect", "--pack", str(pack), "--format", "json"],
        "inspect",
        timeout=60,
    )
    summary = _parse_tool_json(inspect_result, "inspect")
    report = {
        "case": prepared,
        "evaluation": evaluation,
        "replay": replay,
        "summary": summary,
    }
    reports = output_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{case['id']}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (reports / f"{case['id']}.md").write_text(
        render_markdown(summary) + "\n", encoding="utf-8"
    )
    return {
        "case": case["id"],
        "evaluation_status": evaluation.get("status"),
        "evaluation_exit_code": evaluation.get("exit_code", result.returncode),
        "replay_status": replay.get("status"),
        "replay_exit_code": replay.get("tool_return_code"),
        "inspect_status": summary.get("status"),
        "inspect_exit_code": summary.get("tool_return_code"),
        "pack": str(pack),
        "report": str(reports / f"{case['id']}.md"),
    }


def _parse_tool_json(result: ProcessResult, operation: str) -> dict:
    if result.output_exceeded:
        return {
            "status": "error",
            "errors": [f"jev-ci {operation} output exceeded its byte cap"],
            "tool_return_code": result.returncode,
            "stdout_bytes": len(result.stdout),
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        }
    try:
        value = json.loads(result.stdout)
    except (UnicodeError, ValueError):
        value = None
    if not isinstance(value, dict):
        return {
            "status": "error",
            "errors": [f"jev-ci {operation} did not return a JSON summary"],
            "tool_return_code": result.returncode,
            "stdout_bytes": len(result.stdout),
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_bytes": len(result.stderr),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        }
    value["tool_return_code"] = result.returncode
    if result.returncode and value.get("status") != "error":
        value.setdefault("errors", []).append(
            f"jev-ci {operation} exited with code {result.returncode}"
        )
    return value


def _invoke_tool(
    runner: Callable[..., ProcessResult],
    command: list[str],
    operation: str,
    *,
    timeout: float,
) -> ProcessResult:
    try:
        return runner(
            command,
            timeout_seconds=timeout,
            max_output_bytes=OUTPUT_LIMIT,
        )
    except (OSError, TimeoutError) as exc:
        message = f"{operation} could not complete: {type(exc).__name__}"
        return ProcessResult(2, b"", message.encode("utf-8"), False)


def parser() -> argparse.ArgumentParser:
    cases = load_cases()
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--output", type=Path, required=True, help="new output directory")
    root.add_argument(
        "--case",
        choices=tuple(cases),
        action="append",
        help="case to prepare; defaults to all three (repeatable)",
    )
    root.add_argument(
        "--evaluate",
        action="store_true",
        help="make live Gateway calls and write Evidence Packs",
    )
    root.add_argument("--jev-ci", help="installed jev-ci executable")
    root.add_argument(
        "--env-file", type=Path, help="dotenv file passed directly to jev-ci"
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output_root = args.output.expanduser().resolve()
    if output_root.exists():
        raise SystemExit(f"output directory already exists: {output_root}")
    if output_root == PROJECT_ROOT or output_root.is_relative_to(PROJECT_ROOT):
        raise SystemExit("choose an output directory outside the project checkout")
    if args.env_file is not None and not args.evaluate:
        raise SystemExit("--env-file requires explicit --evaluate")
    tool = _tool_command(args.jev_ci) if args.evaluate else None
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir()
    cases = load_cases()
    selected = list(dict.fromkeys(args.case or list(cases)))
    (output_root / ".disabled-hooks").mkdir()
    prepared = []
    for case_id in selected:
        prepared_case = prepare_case(cases[case_id], output_root)
        prepared.append((cases[case_id], prepared_case))
    result = {"prepared": [record for _, record in prepared], "evaluated": []}
    if args.evaluate:
        result["evaluated"] = [
            evaluate_case(
                case,
                record,
                output_root,
                HARNESS_ROOT / "controls",
                tool or [],
                args.env_file,
            )
            for case, record in prepared
        ]
    (output_root / "run-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if any(
        item.get("evaluation_status") == "error"
        or item.get("evaluation_exit_code") == 2
        or item.get("replay_status") != "verified"
        or item.get("replay_exit_code") != 0
        or item.get("inspect_status") == "error"
        or item.get("inspect_exit_code") != 0
        for item in result["evaluated"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (JevCIError, OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"public PR validation failed: {exc}") from exc
