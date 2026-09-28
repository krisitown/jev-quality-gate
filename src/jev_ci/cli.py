"""Portable command-line entry points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .coordinator import evaluate, validate
from .errors import JevCIError
from .trace import inspect_pack, verify_pack


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="jev-ci",
        description="Bounded TypeSafe Jev policy evaluation of committed branch changes",
    )
    commands = root.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "validate", help="validate trusted config and a YAML policy folder"
    )
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--policies", type=Path)
    check.add_argument("--format", choices=("text", "json"), default="text")
    run = commands.add_parser(
        "evaluate", help="evaluate source against the merge base with target"
    )
    run.add_argument("--repo", type=Path, required=True)
    run.add_argument("--source", default="HEAD")
    run.add_argument("--target", default="refs/heads/main")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--policies", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--env-file", type=Path)
    run.add_argument("--format", choices=("text", "json"), default="text")
    show = commands.add_parser("inspect", help="read a saved Evidence Pack")
    show.add_argument("--pack", type=Path, required=True)
    show.add_argument("--format", choices=("text", "json"), default="text")
    replay = commands.add_parser(
        "replay", help="check saved protocol responses and pack integrity"
    )
    replay.add_argument("--pack", type=Path, required=True)
    replay.add_argument("--mode", choices=("protocol",), required=True)
    replay.add_argument("--format", choices=("text", "json"), default="text")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate(args.config, args.policies)
            code = 0
        elif args.command == "evaluate":
            result = evaluate(
                args.repo,
                args.source,
                args.target,
                args.config,
                args.policies,
                args.output,
                args.env_file,
            )
            code = result["exit_code"]
        elif args.command == "inspect":
            result = inspect_pack(args.pack)
            code = 0
        else:
            result = verify_pack(args.pack)
            code = 0
    except JevCIError as exc:
        result = {"status": "error", "errors": [str(exc)]}
        code = 2
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        if code == 2:
            print(
                "jev-ci: " + "; ".join(result.get("errors", ["execution error"])),
                file=sys.stderr,
            )
        else:
            suffix = f"; pack={result['output']}" if "output" in result else ""
            print(f"jev-ci: {result['status']}{suffix}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
