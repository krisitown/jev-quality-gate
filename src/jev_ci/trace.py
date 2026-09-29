"""Append-only events, content-addressed blobs, atomic summaries, and replay checks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import TraceError
from .util import atomic_bytes, atomic_json, canonical, digest


class Pack:
    def __init__(self, path: Path):
        self.path = path
        self.run_id = uuid4().hex
        self.started = time.monotonic()
        self.sequence = 0
        self.blobs: dict[str, dict] = {}
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=False)
            (path / "blobs" / "sha256").mkdir(parents=True)
            self.stream = (path / "events.jsonl").open("ab", buffering=0)
            self.event("run_started", {"run_id": self.run_id})
        except OSError as exc:
            raise TraceError(f"cannot create Evidence Pack: {exc}") from exc

    def blob(self, content: bytes) -> str:
        sha = digest(content)
        path = self.path / "blobs" / "sha256" / sha
        if not path.exists():
            try:
                with path.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                pass
            except OSError as exc:
                raise TraceError("cannot persist Evidence Pack blob") from exc
        self.blobs[sha] = {"bytes": len(content), "encoding": "binary"}
        return sha

    def event(
        self,
        kind: str,
        payload: dict,
        evaluation_id: str | None = None,
        policy_id: str | None = None,
        chunk_id: str | None = None,
    ) -> None:
        self.sequence += 1
        record = {
            "schema_version": "jev.event/0.1",
            "sequence": self.sequence,
            "run_id": self.run_id,
            "time": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - self.started,
            "type": kind,
            "evaluation_id": evaluation_id,
            "policy_id": policy_id,
            "chunk_id": chunk_id,
            "payload": payload,
        }
        try:
            self.stream.write(canonical(record) + b"\n")
            os.fsync(self.stream.fileno())
        except OSError as exc:
            raise TraceError("cannot persist Evidence Pack event") from exc

    def write(self, relative: str, value) -> None:
        atomic_json(self.path / relative, value)

    def write_text(self, relative: str, value: str) -> None:
        atomic_bytes(self.path / relative, value.encode("utf-8"))

    def finish(self, summary: dict) -> None:
        self.write(
            "blobs/manifest.json",
            {"schema_version": "jev.blobs/0.1", "blobs": self.blobs},
        )
        self.write("summary.json", summary)
        self.event(
            "run_finished",
            {"status": summary["status"], "exit_code": summary["exit_code"]},
        )
        self.stream.close()
        checksums = {}
        for file in sorted(self.path.rglob("*")):
            if file.is_file() and file.name != "checksums.json":
                checksums[file.relative_to(self.path).as_posix()] = digest(
                    file.read_bytes()
                )
        atomic_json(
            self.path / "checksums.json",
            {"schema_version": "jev.checksums/0.1", "files": checksums},
        )


def inspect_pack(path: Path) -> dict:
    try:
        summary = json.loads((path / "summary.json").read_bytes())
        return summary
    except (OSError, ValueError) as exc:
        raise TraceError(f"cannot inspect pack: {exc}") from exc


def verify_pack(path: Path) -> dict:
    """Compatibility wrapper for the Evidence Pack replay verifier."""
    from .replay import verify_pack as replay_verify_pack

    return replay_verify_pack(path)
