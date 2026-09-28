"""Append-only events, content-addressed blobs, atomic summaries, and replay checks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import TraceError
from .util import atomic_json, canonical, digest


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
    try:
        checksums = json.loads((path / "checksums.json").read_bytes())["files"]
        actual = {
            file.relative_to(path).as_posix(): digest(file.read_bytes())
            for file in path.rglob("*")
            if file.is_file() and file.name != "checksums.json"
        }
        if actual != checksums:
            raise TraceError("Evidence Pack checksum mismatch")
        blob_manifest = json.loads((path / "blobs" / "manifest.json").read_bytes())[
            "blobs"
        ]
        for sha, metadata in blob_manifest.items():
            content = (path / "blobs" / "sha256" / sha).read_bytes()
            if digest(content) != sha or len(content) != metadata["bytes"]:
                raise TraceError("Evidence Pack blob identity mismatch")
        records = [
            json.loads(line)
            for line in (path / "events.jsonl").read_bytes().splitlines()
        ]
        if (
            not records
            or records[-1]["type"] != "run_finished"
            or [row["sequence"] for row in records] != list(range(1, len(records) + 1))
        ):
            raise TraceError("Evidence Pack event sequence incomplete")
        from .inference import validate_answers

        count = 0
        for row in records:
            if row["type"] == "model_response":
                request = json.loads(
                    (
                        path / "blobs" / "sha256" / row["payload"]["request_blob"]
                    ).read_bytes()
                )
                response = json.loads(
                    (
                        path / "blobs" / "sha256" / row["payload"]["response_blob"]
                    ).read_bytes()
                )
                if (
                    validate_answers(response, request["questions"])
                    != row["payload"]["validated"]
                ):
                    raise TraceError("replayed typed answers differ")
                count += 1
        summary = inspect_pack(path)
        if summary["status"] != records[-1]["payload"]["status"]:
            raise TraceError("replayed status differs")
        replayed_aggregates = 0
        if (path / "policies" / "manifest.json").exists() and summary.get("policies"):
            from .aggregation import aggregate, run_status
            from .policy import Policy, parse_policy_yaml

            policy_manifest = json.loads(
                (path / "policies" / "manifest.json").read_bytes()
            )
            config_sha = json.loads((path / "manifest.json").read_bytes())[
                "config_sha256"
            ]
            config = json.loads((path / "blobs" / "sha256" / config_sha).read_bytes())
            by_id = {item["id"]: item for item in policy_manifest["files"]}
            for stored in summary["policies"]:
                entry = by_id[stored["policy_id"]]
                raw = (path / "blobs" / "sha256" / entry["raw_sha256"]).read_bytes()
                policy = Policy(entry["path"], raw, parse_policy_yaml(raw))
                units = [
                    json.loads(
                        (path / "evaluations" / unit_id / "result.json").read_bytes()
                    )
                    for unit_id in stored["completed_units"]
                ]
                recon = (
                    json.loads(
                        (
                            path
                            / "evaluations"
                            / stored["reconciliation_id"]
                            / "result.json"
                        ).read_bytes()
                    )
                    if stored["reconciliation_id"]
                    else None
                )
                actual = aggregate(
                    policy,
                    units,
                    recon,
                    stored["expected_chunks"],
                    stored["unsupported_content"],
                    stored["incomplete_coverage"],
                )
                if (
                    actual["outcome"] == "uncertain"
                    and config["ci"]["incomplete"] == "block"
                ):
                    actual["action"] = "block"
                if actual != stored or actual != json.loads(
                    (path / "policies" / policy.id / "aggregate.json").read_bytes()
                ):
                    raise TraceError(f"replayed aggregate differs: {policy.id}")
                replayed_aggregates += 1
            status, code = run_status(summary["policies"], summary["errors"])
            if config["mode"] == "calibration" and status == "blocked":
                status, code = "completed_with_findings", 0
            if status != summary["status"] or code != summary["exit_code"]:
                raise TraceError("replayed CI outcome differs")
        return {
            "status": "verified",
            "validated_responses": count,
            "replayed_aggregates": replayed_aggregates,
            "run_status": summary["status"],
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TraceError(f"protocol replay failed: {exc}") from exc
