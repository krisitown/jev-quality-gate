"""Immutable branch comparison; no implicit fetch or working-tree reads."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

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


def _git(
    repo: Path,
    *args: str,
    max_bytes: int = 8 * 1024 * 1024,
    deadline: float | None = None,
) -> bytes:
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
        timeout = 30.0 if deadline is None else min(30.0, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("Git deadline expired")
        process = run_bounded(
            command,
            env=env,
            timeout_seconds=timeout,
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


def iter_tree_blobs(
    repo: Path,
    commit: str,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    paths: set[str] | None = None,
    path_filter: Callable[[str], bool] | None = None,
    deadline: float | None = None,
    stats: dict | None = None,
) -> Iterator[tuple[str, str, bytes]]:
    """Read regular committed blobs with a bounded number of Git processes.

    The tree inventory and `cat-file --batch-check` determine which blobs fit
    before content is requested. The content batch is therefore bounded by
    `max_total_bytes`; oversized, unsupported and over-budget files are counted
    in `stats` and omitted. A deadline bounds each Git operation.
    """
    report = stats if stats is not None else {}
    report.update(
        partial=False,
        skipped_files=0,
        skipped_paths=[],
        bytes_read=0,
        limit_reason=None,
    )

    def remaining() -> float:
        if deadline is None:
            return 60.0
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Git blob scan deadline expired")
        return value

    repo = repo.resolve()
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_EXTERNAL_DIFF": "",
            "GIT_PAGER": "cat",
        }
    )
    prefix = [
        "git",
        "-C",
        str(repo),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
    ]

    def run_git(args: list[str], input_bytes: bytes, cap: int) -> bytes:
        try:
            process = run_bounded(
                args,
                env=env,
                input_bytes=input_bytes,
                timeout_seconds=remaining(),
                max_output_bytes=cap,
            )
        except TimeoutError as exc:
            raise TimeoutError("Git blob scan deadline expired") from exc
        except OSError as exc:
            raise ComparisonError(
                f"Git blob scan failed: {type(exc).__name__}"
            ) from exc
        if process.output_exceeded:
            raise ComparisonError("Git blob scan output exceeds byte cap")
        if process.returncode:
            raise ComparisonError(
                "Git blob scan failed: "
                + process.stderr.decode("utf-8", "replace").strip()
            )
        return process.stdout

    try:
        inventory = _git(
            repo,
            "ls-tree",
            "-r",
            "-z",
            commit,
            max_bytes=16 * 1024 * 1024,
            deadline=deadline,
        )
    except ComparisonError as exc:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Git blob scan deadline expired") from exc
        raise
    eligible: list[tuple[str, str]] = []
    for record in inventory.split(b"\0"):
        remaining()
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ComparisonError(
                "Git tree contains malformed or undecodable entry"
            ) from exc
        if not path or path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise ComparisonError("Git tree contains unsafe path")
        if paths is not None and path not in paths:
            continue
        if path_filter is not None and not path_filter(path):
            continue
        if mode not in ("100644", "100755") or kind != "blob":
            report["partial"] = True
            report["skipped_files"] += 1
            report["skipped_paths"].append(path)
            continue
        eligible.append((path, oid))

    if not eligible:
        return
    check_input = b"".join(oid.encode("ascii") + b"\n" for _, oid in eligible)
    checked = run_git(
        prefix
        + ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        check_input,
        32 * 1024 * 1024,
    )
    check_rows = checked.splitlines()
    if len(check_rows) != len(eligible):
        raise ComparisonError("Git returned an incomplete blob size inventory")
    selected: list[tuple[str, str, int]] = []
    total = 0
    for (path, expected_oid), row in zip(eligible, check_rows):
        remaining()
        try:
            oid, kind, size_text = row.decode("ascii").split()
            size = int(size_text)
        except (ValueError, UnicodeError) as exc:
            raise ComparisonError("Git returned malformed blob size metadata") from exc
        if oid != expected_oid or kind != "blob" or size < 0:
            raise ComparisonError("Git blob identity changed during scan")
        if size > max_file_bytes or total + size > max_total_bytes:
            report["partial"] = True
            report["skipped_files"] += 1
            report["skipped_paths"].append(path)
            report["limit_reason"] = "search_byte_limit"
            continue
        selected.append((path, oid, size))
        total += size
    if not selected:
        return
    batch_input = b"".join(oid.encode("ascii") + b"\n" for _, oid, _ in selected)
    batch = run_git(
        prefix + ["cat-file", "--batch"],
        batch_input,
        max_total_bytes + len(selected) * 128,
    )
    offset = 0
    for path, oid, size in selected:
        remaining()
        try:
            newline = batch.index(b"\n", offset)
            header = batch[offset:newline].decode("ascii").split()
            if (
                len(header) != 3
                or header[0] != oid
                or header[1] != "blob"
                or int(header[2]) != size
            ):
                raise ValueError("mismatched batch header")
            start, end = newline + 1, newline + 1 + size
            if end >= len(batch) or batch[end : end + 1] != b"\n":
                raise ValueError("truncated batch content")
            content = batch[start:end]
        except (ValueError, UnicodeError) as exc:
            raise ComparisonError("Git returned malformed batch blob data") from exc
        report["bytes_read"] += size
        offset = end + 1
        yield path, oid, content
    if offset != len(batch):
        raise ComparisonError("Git returned trailing batch blob data")


def resolve_commit(repo: Path, ref: str, *, deadline: float | None = None) -> str:
    if not ref or ref.startswith("-"):
        raise ComparisonError("invalid Git ref")
    return (
        _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", deadline=deadline)
        .decode()
        .strip()
    )


def compare(
    repo: Path,
    source_ref: str,
    target_ref: str,
    max_diff_bytes: int,
    *,
    deadline: float | None = None,
) -> Comparison:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ComparisonError("repository directory does not exist")
    if _git(
        repo, "rev-parse", "--show-toplevel", deadline=deadline
    ).decode().strip() != str(repo):
        raise ComparisonError("--repo must name the Git repository root")
    source = resolve_commit(repo, source_ref, deadline=deadline)
    target = resolve_commit(repo, target_ref, deadline=deadline)
    bases = (
        _git(repo, "merge-base", "--all", target, source, deadline=deadline)
        .decode()
        .splitlines()
    )
    if len(bases) != 1:
        raise ComparisonError(f"expected one merge base, found {len(bases)}")
    base = bases[0]
    trees = [
        _git(repo, "rev-parse", f"{commit}^{{tree}}", deadline=deadline)
        .decode()
        .strip()
        for commit in (source, target, base)
    ]
    dirty = bool(_git(repo, "status", "--porcelain=v1", "-z", deadline=deadline))
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
        deadline=deadline,
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
        deadline=deadline,
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
        timeout = 60.0 if deadline is None else min(60.0, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("Git deadline expired")
        process = run_bounded(
            command, env=env, max_output_bytes=max_diff_bytes, timeout_seconds=timeout
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
    comparison: Comparison,
    snapshot: str,
    path: str,
    max_bytes: int,
    *,
    deadline: float | None = None,
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
    entry = _git(
        comparison.repo, "ls-tree", "-z", commit, "--", path, deadline=deadline
    )
    records = [part for part in entry.split(b"\0") if part]
    matches = [
        record for record in records if record.split(b"\t", 1)[-1] == path.encode()
    ]
    if len(matches) != 1 or not matches[0].startswith(
        (b"100644 blob ", b"100755 blob ")
    ):
        raise ComparisonError("file missing or unsupported object type")
    blob = matches[0].split(b" ", 2)[2].split(b"\t", 1)[0].decode("ascii")
    size = int(
        _git(comparison.repo, "cat-file", "-s", blob, deadline=deadline).decode()
    )
    if size > max_bytes:
        raise ComparisonError("file exceeds evidence byte cap")
    return _git(
        comparison.repo,
        "cat-file",
        "blob",
        blob,
        max_bytes=max_bytes,
        deadline=deadline,
    )
