"""Immutable branch comparison; no implicit fetch or working-tree reads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ComparisonError
from .process import run_bounded
from .util import digest


@dataclass(frozen=True)
class Comparison:
    repo: Path
    source_ref: str
    target_ref: str
    source: str
    target: str
    base: str
    source_tree: str
    target_tree: str
    base_tree: str
    dirty: bool
    paths: tuple[str, ...]
    unsupported_paths: tuple[str, ...]
    raw_diff: bytes
    diff_exceeded: bool

    def descriptor(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "source": self.source,
            "target": self.target,
            "base": self.base,
            "source_tree": self.source_tree,
            "target_tree": self.target_tree,
            "base_tree": self.base_tree,
            "dirty_worktree_excluded": self.dirty,
            "paths": list(self.paths),
            "unsupported_paths": list(self.unsupported_paths),
            "raw_diff_sha256": digest(self.raw_diff),
            "diff_exceeded": self.diff_exceeded,
        }


def _git(repo: Path, *args: str, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_EXTERNAL_DIFF": "",
            "GIT_PAGER": "cat",
        }
    )
    command = [
        "git",
        "-C",
        str(repo),
        "-c",
        "diff.external=",
        "-c",
        "core.quotePath=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        *args,
    ]
    try:
        process = run_bounded(
            command,
            env=env,
            timeout_seconds=30,
            max_output_bytes=max_bytes,
        )
    except (OSError, TimeoutError) as exc:
        raise ComparisonError(f"Git command failed: {type(exc).__name__}") from exc
    if process.returncode:
        message = process.stderr.decode("utf-8", "replace")[:300].strip()
        raise ComparisonError(f"Git comparison failed: {message}")
    if process.output_exceeded:
        raise ComparisonError("Git metadata exceeds configured limit")
    return process.stdout


def resolve_commit(repo: Path, ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise ComparisonError("invalid Git ref")
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def compare(
    repo: Path, source_ref: str, target_ref: str, max_diff_bytes: int
) -> Comparison:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ComparisonError("repository directory does not exist")
    if _git(repo, "rev-parse", "--show-toplevel").decode().strip() != str(repo):
        raise ComparisonError("--repo must name the Git repository root")
    source, target = resolve_commit(repo, source_ref), resolve_commit(repo, target_ref)
    bases = _git(repo, "merge-base", "--all", target, source).decode().splitlines()
    if len(bases) != 1:
        raise ComparisonError(f"expected one merge base, found {len(bases)}")
    base = bases[0]
    trees = [
        _git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
        for commit in (source, target, base)
    ]
    dirty = bool(_git(repo, "status", "--porcelain=v1", "-z"))
    inventory = _git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--raw",
        "-z",
        base,
        source,
        max_bytes=max(16 * 1024 * 1024, max_diff_bytes * 2),
    )
    try:
        records = [part for part in inventory.split(b"\0") if part]
        if len(records) % 2:
            raise ValueError("malformed raw inventory")
        paths = tuple(records[i + 1].decode("utf-8") for i in range(0, len(records), 2))
    except UnicodeError as exc:
        raise ComparisonError("changed path cannot be decoded as UTF-8") from exc
    except ValueError as exc:
        raise ComparisonError("malformed Git path inventory") from exc
    numstat = _git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--numstat",
        "-z",
        base,
        source,
        max_bytes=max(16 * 1024 * 1024, max_diff_bytes * 2),
    )
    unsupported = []
    for row in numstat.split(b"\0"):
        if not row:
            continue
        parts = row.split(b"\t", 2)
        if len(parts) == 3 and parts[0] == b"-" and parts[1] == b"-":
            unsupported.append(parts[2].decode("utf-8", "replace"))
    # Raw inventory carries old/new object modes without per-path subprocesses.
    for i, path in zip(range(0, len(records), 2), paths):
        parts = records[i].split()
        if len(parts) < 5 or not parts[0].startswith(b":"):
            raise ComparisonError("malformed Git raw inventory entry")
        old_mode, new_mode = parts[0][1:], parts[1]
        if any(
            mode not in (b"000000", b"100644", b"100755")
            for mode in (old_mode, new_mode)
        ):
            unsupported.append(path)
    env = os.environ.copy()
    env.update(
        {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_EXTERNAL_DIFF": ""}
    )
    command = [
        "git",
        "-C",
        str(repo),
        "-c",
        "diff.external=",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--no-renames",
        "--diff-algorithm=myers",
        "--unified=3",
        "--binary",
        base,
        source,
    ]
    try:
        process = run_bounded(
            command, env=env, max_output_bytes=max_diff_bytes, timeout_seconds=60
        )
        raw = process.stdout
        exceeded = process.output_exceeded
        if not exceeded and process.returncode:
            raise ComparisonError(
                f"Git diff failed: {process.stderr.decode('utf-8', 'replace')[:300]}"
            )
    except (OSError, TimeoutError) as exc:
        raise ComparisonError(f"Git diff failed: {type(exc).__name__}") from exc
    return Comparison(
        repo,
        source_ref,
        target_ref,
        source,
        target,
        base,
        *trees,
        dirty,
        paths,
        tuple(sorted(set(unsupported))),
        raw,
        exceeded,
    )


def show_file(
    comparison: Comparison, snapshot: str, path: str, max_bytes: int
) -> bytes:
    if snapshot not in ("head", "base", "target"):
        raise ComparisonError("unknown snapshot")
    if not path or path.startswith("/") or ".." in Path(path).parts or "\\" in path:
        raise ComparisonError("unsafe repository path")
    commit = {
        "head": comparison.source,
        "base": comparison.base,
        "target": comparison.target,
    }[snapshot]
    # Git's -- path form avoids ambiguous rev:path syntax and option injection.
    entry = _git(comparison.repo, "ls-tree", "-z", commit, "--", path)
    records = [part for part in entry.split(b"\0") if part]
    matches = [
        record for record in records if record.split(b"\t", 1)[-1] == path.encode()
    ]
    if len(matches) != 1 or not matches[0].startswith(
        (b"100644 blob ", b"100755 blob ")
    ):
        raise ComparisonError("file missing or unsupported object type")
    blob = matches[0].split(b" ", 2)[2].split(b"\t", 1)[0].decode("ascii")
    size = int(_git(comparison.repo, "cat-file", "-s", blob).decode())
    if size > max_bytes:
        raise ComparisonError("file exceeds evidence byte cap")
    return _git(comparison.repo, "cat-file", "blob", blob, max_bytes=max_bytes)
