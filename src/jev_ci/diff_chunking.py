"""The sole owner of diff segmentation, caps, ranges, and chunk identities."""

from __future__ import annotations

from dataclasses import dataclass

from .git import Comparison
from .util import canonical, digest

STRATEGY = "bounded-sequential-v1"


@dataclass(frozen=True)
class DiffChunk:
    id: str
    ordinal: int
    start: int
    end: int
    paths: tuple[str, ...]
    content: str
    continuation_before: bool
    continuation_after: bool

    def envelope(self) -> dict:
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "start": self.start,
            "end": self.end,
            "paths": list(self.paths),
            "content": self.content,
            "continuation_before": self.continuation_before,
            "continuation_after": self.continuation_after,
        }


@dataclass(frozen=True)
class ChunkManifest:
    status: str
    reason: str | None
    chunks: tuple[DiffChunk, ...]
    summary: dict

    def read_chunk(self, chunk_id: str) -> DiffChunk:
        for chunk in self.chunks:
            if chunk.id == chunk_id:
                return chunk
        raise KeyError(chunk_id)


def _end_of_utf8(data: bytes, start: int, end: int) -> int:
    while end > start:
        try:
            data[start:end].decode("utf-8")
            return end
        except UnicodeDecodeError as exc:
            if exc.start < end - start - 4:
                raise
            end -= 1
    return start


def chunk_diff(change: Comparison, limits: dict) -> ChunkManifest:
    raw = change.raw_diff
    common = {
        "schema_version": "jev.chunks/0.1",
        "strategy": STRATEGY,
        "diff_sha256": digest(raw),
        "total_raw_bytes": len(raw),
        "caps": limits,
        "source": change.source,
        "base": change.base,
        "unsupported_paths": list(change.unsupported_paths),
    }
    if change.diff_exceeded:
        return ChunkManifest(
            "incomplete", "diff_limit_exceeded", (), {**common, "chunks": []}
        )
    if not raw:
        return ChunkManifest("complete", None, (), {**common, "chunks": []})
    headers = []
    marker = b"diff --git "
    if not raw.startswith(marker):
        return ChunkManifest(
            "incomplete", "unrecognized_diff_format", (), {**common, "chunks": []}
        )
    at = 0
    while at < len(raw):
        headers.append(at)
        next_at = raw.find(b"\n" + marker, at + 1)
        if next_at < 0:
            break
        at = next_at + 1
    if len(headers) != len(change.paths):
        return ChunkManifest(
            "incomplete", "path_inventory_mismatch", (), {**common, "chunks": []}
        )
    sections = [
        (
            headers[i],
            headers[i + 1] if i + 1 < len(headers) else len(raw),
            change.paths[i],
        )
        for i in range(len(headers))
    ]
    chunks = []
    cap = limits["max_chunk_bytes"]
    for section_start, section_end, path in sections:
        at = section_start
        while at < section_end:
            ordinal = len(chunks)
            if ordinal >= limits["max_chunks"]:
                return ChunkManifest(
                    "incomplete",
                    "chunk_count_exceeded",
                    tuple(chunks),
                    {**common, "chunks": [c.envelope() for c in chunks]},
                )

            # IDs are fixed-width hashes; size test includes the serialized envelope and metadata.
            def make(end: int) -> DiffChunk | None:
                try:
                    content = raw[at:end].decode("utf-8")
                except UnicodeDecodeError:
                    return None
                identity = {
                    "strategy": STRATEGY,
                    "base": change.base,
                    "source": change.source,
                    "cap": cap,
                    "start": at,
                    "end": end,
                    "path": path,
                    "payload_sha256": digest(raw[at:end]),
                }
                chunk = DiffChunk(
                    digest(canonical(identity)),
                    ordinal,
                    at,
                    end,
                    (path,),
                    content,
                    at > section_start,
                    end < section_end,
                )
                if len(canonical(chunk.envelope())) > cap:
                    return None
                return chunk

            low, high, best = at + 1, min(section_end, at + cap), None
            while low <= high:
                mid = (low + high) // 2
                mid = _end_of_utf8(raw, at, mid)
                candidate = make(mid) if mid > at else None
                if candidate:
                    best = candidate
                    low = mid + 1
                else:
                    high = mid - 1
            if best is None:
                return ChunkManifest(
                    "incomplete",
                    "chunk_metadata_too_large_or_undecodable",
                    tuple(chunks),
                    {**common, "chunks": [c.envelope() for c in chunks]},
                )
            # Prefer a complete line when one fits; long UTF-8 lines remain byte-contiguous.
            last_newline = raw.rfind(b"\n", at, best.end)
            if last_newline >= at and last_newline + 1 < best.end:
                line_chunk = make(last_newline + 1)
                if line_chunk:
                    best = line_chunk
            chunks.append(best)
            at = best.end
    if b"".join(raw[c.start : c.end] for c in chunks) != raw:
        return ChunkManifest(
            "incomplete",
            "reconstruction_failed",
            tuple(chunks),
            {**common, "chunks": [c.envelope() for c in chunks]},
        )
    return ChunkManifest(
        "complete",
        None,
        tuple(chunks),
        {**common, "chunks": [c.envelope() for c in chunks]},
    )
