"""Pinned Ripwire 0.6.5 adapter for bounded, explicitly partial graph evidence."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import ComparisonError
from .git import Comparison, iter_tree_blobs
from .process import run_bounded
from .util import digest


class RipwireProvider:
    def __init__(
        self, comparison: Comparison, settings: dict, *, deadline: float | None = None
    ):
        self.comparison = comparison
        self.settings = settings
        self.deadline = deadline
        self._temp: tempfile.TemporaryDirectory | None = None
        self.root: Path | None = None
        self.map: dict[str, Any] | None = None
        self.last_raw: bytes = b""
        self.snapshot_skipped: list[str] = []

    def _timeout(self) -> float:
        timeout = self.settings["timeout_seconds"]
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("Ripwire deadline expired")
        return timeout

    def describe(self) -> dict:
        return {
            "id": "ripwire",
            "version": self.settings["version"],
            "binary_sha256": self.settings["sha256"],
            "license": "Apache-2.0",
            "capabilities": ["GET_CALLERS", "GET_CALLEES"],
            "precision": "heuristic",
            "coverage": "partial",
            "snapshot_commit": self.comparison.source,
            "snapshot_skipped": self.snapshot_skipped,
        }

    def __enter__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="jev-ci-ripwire-")
        self.root = Path(self._temp.name).resolve()
        try:
            version = run_bounded(
                [self.settings["binary"], "--version"],
                max_output_bytes=2048,
                timeout_seconds=self._timeout(),
            )
            if (
                version.returncode
                or version.output_exceeded
                or not version.stdout.decode("utf-8", "replace").startswith(
                    f"ripwire {self.settings['version']} "
                )
            ):
                raise ComparisonError(
                    "Ripwire binary version does not match pinned adapter"
                )
            self._materialize_snapshot()
            self.map = self._run("--json", f"--top-k={self.settings['max_symbols']}")
            if (
                not isinstance(self.map.get("r"), list)
                or any(
                    isinstance(self.map.get(key), bool)
                    or not isinstance(self.map.get(key), int)
                    or self.map[key] < 0
                    for key in ("files", "symbols", "shown")
                )
                or self.map["shown"] > self.map["symbols"]
            ):
                raise ComparisonError("Ripwire map has an unsupported JSON schema")
        except (
            OSError,
            TimeoutError,
            ValueError,
            ComparisonError,
        ) as exc:
            self.__exit__(None, None, None)
            raise ComparisonError(
                f"Ripwire preparation failed: {type(exc).__name__}: {exc}"
            ) from exc
        return self

    def _materialize_snapshot(self) -> None:
        """Read committed blobs directly; Git archive export-ignore may hide candidate files."""
        assert self.root is not None
        stats: dict = {}
        for path, _blob, content in iter_tree_blobs(
            self.comparison.repo,
            self.comparison.source,
            max_file_bytes=self.settings["max_snapshot_bytes"],
            max_total_bytes=self.settings["max_snapshot_bytes"],
            deadline=self.deadline,
            stats=stats,
        ):
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise TimeoutError("Ripwire snapshot deadline expired")
            relative = Path(path)
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.resolve().is_relative_to(self.root):
                raise ComparisonError("Git snapshot path escapes temporary root")
            destination.write_bytes(content)
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("Ripwire snapshot deadline expired")
        self.snapshot_skipped = stats["skipped_paths"]
        if stats["limit_reason"]:
            raise ComparisonError("Ripwire snapshot bytes exceed cap")

    def __exit__(self, *_):
        if self._temp:
            self._temp.cleanup()
            self._temp = None

    def _run(self, *flags: str) -> dict:
        assert self.root is not None
        command = [self.settings["binary"], ".", *flags]
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
        }
        try:
            process = run_bounded(
                command,
                cwd=self.root,
                env=env,
                max_output_bytes=self.settings["max_output_bytes"],
                timeout_seconds=self._timeout(),
            )
            if process.output_exceeded:
                raise ComparisonError("Ripwire output exceeds cap")
            if process.returncode:
                raise ComparisonError(
                    f"Ripwire failed: {process.stderr.decode('utf-8', 'replace')[:200]}"
                )
            result = json.loads(process.stdout)
            if not isinstance(result, dict):
                raise ValueError("Ripwire returned non-object JSON")
            self.last_raw = process.stdout
            return result
        except (OSError, TimeoutError, ValueError, ComparisonError) as exc:
            raise ComparisonError(
                f"Ripwire query failed: {type(exc).__name__}: {exc}"
            ) from exc

    def changed_symbols(self, paths: tuple[str, ...]) -> tuple[list[dict], dict]:
        assert self.map is not None
        symbols = []
        for row in self.map.get("r", []):
            if isinstance(row, dict) and row.get("p") in paths:
                for symbol in row.get("s", []):
                    if isinstance(symbol, dict) and isinstance(symbol.get("n"), str):
                        symbols.append(
                            {
                                "path": row["p"],
                                "name": symbol["n"],
                                "kind": symbol.get("t"),
                            }
                        )
        return symbols, {
            "shown": self.map.get("shown"),
            "total": self.map.get("symbols"),
            "partial": self.map.get("shown") != self.map.get("symbols")
            or bool(self.snapshot_skipped),
            "snapshot_skipped": self.snapshot_skipped,
        }

    def relation(self, kind: str, name: str) -> dict:
        if (
            kind not in ("GET_CALLERS", "GET_CALLEES")
            or not name
            or len(name) > 200
            or name.startswith("-")
        ):
            raise ValueError("invalid Ripwire relationship request")
        key = "callers" if kind == "GET_CALLERS" else "callees"
        raw = self._run(f"--{key}={name}", "--json")
        if (
            raw.get("of") != name
            or not isinstance(raw.get(key), list)
            or any(
                isinstance(raw.get(field), bool)
                or not isinstance(raw.get(field), int)
                or raw[field] < 0
                for field in ("defs", "count")
            )
        ):
            raise ComparisonError("Ripwire response does not match request")
        rows = raw[key]
        safe_rows = []
        for row in rows:
            if not isinstance(row, dict) or not all(
                isinstance(row.get(field), str) for field in ("n", "p")
            ):
                raise ComparisonError("Ripwire relationship row is malformed")
            safe_rows.append(
                {"name": row["n"], "location": row["p"], "kind": row.get("t")}
            )
        return {
            "provider": "ripwire",
            "version": self.settings["version"],
            "binary_sha256": self.settings["sha256"],
            "snapshot": self.comparison.source,
            "query": name,
            "relation": key,
            "items": safe_rows,
            "count": raw.get("count"),
            "definitions": raw.get("defs"),
            "coverage": "partial",
            "counts_floor": raw.get("counts_floor", True),
            "graph_ambiguous": raw.get("graph_ambiguous"),
            "graph_unresolved": raw.get("graph_unresolved"),
            "raw_sha256": digest(self.last_raw),
            "raw_stdout": self.last_raw.decode("utf-8"),
            "raw": raw,
        }
