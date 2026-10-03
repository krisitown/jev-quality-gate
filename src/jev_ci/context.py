"""Concrete, immutable evidence menus and bounded retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import zip_longest
from pathlib import Path
import time
from typing import Any

from .config import Config
from .diff_chunking import ChunkManifest, DiffChunk
from .errors import ComparisonError, ProviderError
from .git import Comparison, _git, iter_tree_blobs, show_file
from .policy import Policy
from .providers import RipwireProvider
from .util import canonical, digest


@dataclass(frozen=True)
class Candidate:
    id: str
    request: dict[str, Any]
    purpose: str

    def public(self) -> dict:
        return {"id": self.id, "request": self.request, "purpose": self.purpose}


def candidates(
    policy: Policy,
    change: Comparison,
    chunks: ChunkManifest,
    current: DiffChunk | None,
    delivered: set[str],
    config: Config,
    provider: RipwireProvider | None,
    *,
    deadline: float | None = None,
    evidence: dict[str, Any] | None = None,
) -> tuple[list[Candidate], dict]:
    proposed: list[tuple[str, dict, str]] = []

    def add(kind: str, target: dict, purpose: str):
        if kind in policy.data["evidence"]["allowed_requests"]:
            proposed.append((kind, target, purpose))

    relevant = [path for path in change.paths if policy.matches(path)]
    head_paths = _head_paths(str(change.repo), change.source, deadline)
    for path in relevant:
        snapshot = "base" if path not in head_paths else "head"
        add(
            "GET_FILE",
            {"path": path, "snapshot": snapshot},
            f"Read committed {snapshot} file containing the change",
        )
    # A literal search is useful as a locator, but line excerpts alone are
    # often too little evidence for a semantic policy. Let Jev follow a
    # policy-scoped match to the exact committed file in a later bounded round.
    for item_evidence in (evidence or {}).values():
        if item_evidence.get("type") != "SEARCH_CODE":
            continue
        for item in item_evidence.get("items", []):
            path = item.get("path")
            if not isinstance(path, str) or not policy.matches(path):
                continue
            snapshot = "head"
            add(
                "GET_FILE",
                {"path": path, "snapshot": snapshot},
                f"Read {snapshot} source file located by literal search: {path}",
            )
    provider_coverage = None
    if provider:
        symbols, provider_coverage = provider.changed_symbols(tuple(relevant))
        for symbol in symbols:
            if symbol["kind"] not in ("method", "func", "function"):
                continue
            for kind in ("GET_CALLERS", "GET_CALLEES"):
                add(
                    kind,
                    {"symbol": symbol["name"], "path": symbol["path"]},
                    "Inspect heuristic source relationship",
                )
    for chunk in chunks.chunks:
        if chunk.id != (current.id if current else None) and any(
            path in relevant for path in chunk.paths
        ):
            add(
                "GET_DIFF_CHUNK",
                {"chunk_id": chunk.id},
                "Inspect changed path(s): " + ", ".join(chunk.paths),
            )
    for term in policy.data["discovery"]["search_terms"]:
        add(
            "SEARCH_CODE",
            {"literal": term, "snapshot": "head"},
            "Find authored term in committed source",
        )
    for doc in policy.data["documents"]:
        add("GET_DOCUMENT", {"binding_id": doc}, "Read trusted policy convention")
    dedup = {}
    for kind, target, purpose in proposed:
        request = {"type": kind, "target": target}
        identifier = digest(canonical(request))[:16]
        if identifier not in delivered:
            dedup[identifier] = Candidate(identifier, request, purpose)
    # Keep current-file context first, then share the remaining slots across
    # evidence categories. A large changed-file or symbol inventory must not
    # hide every authored search or adjacent diff request from the model.
    local_paths = set(current.paths) if current else set()
    local_files = []
    groups: dict[str, list[Candidate]] = {
        "SEARCH_CODE": [],
        "relations": [],
        "GET_DIFF_CHUNK": [],
        "GET_FILE": [],
        "GET_DOCUMENT": [],
    }
    for candidate in dedup.values():
        kind = candidate.request["type"]
        if kind == "GET_FILE" and candidate.request["target"]["path"] in local_paths:
            local_files.append(candidate)
        else:
            group = "relations" if kind in ("GET_CALLERS", "GET_CALLEES") else kind
            groups[group].append(candidate)
    items = local_files + [
        candidate
        for row in zip_longest(*groups.values())
        for candidate in row
        if candidate is not None
    ]
    maximum = config.limits["max_candidates"]
    shown = items[:maximum]
    return shown, {
        "ordering": "current-file-then-category-round-robin-v1",
        "total": len(items),
        "shown": len(shown),
        "omitted": len(items) - len(shown),
        "sha256": digest(canonical([x.public() for x in shown])),
        "provider_symbol_map": provider_coverage,
    }


@lru_cache(maxsize=8)
def _head_paths(
    repo: str, source: str, deadline: float | None = None
) -> frozenset[str]:
    raw = _git(
        Path(repo),
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        source,
        max_bytes=16 * 1024 * 1024,
        deadline=deadline,
    )
    return frozenset(
        part.decode("utf-8", "replace") for part in raw.split(b"\0") if part
    )


def retrieve(
    candidate: Candidate,
    policy: Policy,
    change: Comparison,
    chunks: ChunkManifest,
    config: Config,
    provider: RipwireProvider | None,
    *,
    deadline: float | None = None,
) -> dict:
    kind = candidate.request["type"]
    target = candidate.request["target"]
    cap = min(
        config.limits["max_evidence_bytes"],
        policy.data["evidence"]["max_evidence_bytes"],
    )
    result: dict[str, Any] = {
        "candidate_id": candidate.id,
        "type": kind,
        "target": target,
        "status": "unsupported",
        "items": [],
        "coverage": "unknown",
    }
    try:
        if kind == "GET_DIFF_CHUNK":
            chunk = chunks.read_chunk(target["chunk_id"])
            result.update(
                status="ok",
                items=[
                    {
                        "id": chunk.id,
                        "content": chunk.envelope(),
                        "precision": "source_exact",
                    }
                ],
                coverage="complete_for_declared_scope",
            )
        elif kind == "GET_DOCUMENT":
            doc = config.documents[target["binding_id"]]
            content = doc["content"]
            if len(content.encode()) > cap:
                result.update(
                    status="partial",
                    coverage="partial",
                    warnings=["document exceeds evidence cap"],
                )
            else:
                result.update(
                    status="ok",
                    items=[
                        {
                            "id": target["binding_id"],
                            "content": content,
                            "sha256": doc["sha256"],
                            "control_revision": config.data["control_bundle"][
                                "revision"
                            ],
                            "precision": "source_exact",
                        }
                    ],
                    coverage="complete_for_declared_scope",
                )
        elif kind == "GET_FILE":
            path = target["path"]
            if not policy.matches(path):
                result.update(status="denied")
            else:
                raw_content = show_file(
                    change, target["snapshot"], path, cap, deadline=deadline
                )
                if b"\0" in raw_content:
                    result.update(
                        status="partial",
                        coverage="partial",
                        warnings=["binary file cannot be represented as source text"],
                    )
                else:
                    content = raw_content.decode("utf-8")
                    result.update(
                        status="ok",
                        items=[
                            {
                                "id": candidate.id,
                                "path": path,
                                "snapshot": target["snapshot"],
                                "commit": {
                                    "head": change.source,
                                    "base": change.base,
                                    "target": change.target,
                                }[target["snapshot"]],
                                "content": content,
                                "sha256": digest(content.encode()),
                                "precision": "source_exact",
                            }
                        ],
                        coverage="complete_for_declared_scope",
                    )
        elif kind == "SEARCH_CODE":
            literal = target["literal"]
            snapshot = target["snapshot"]
            commit = {
                "head": change.source,
                "base": change.base,
                "target": change.target,
            }[snapshot]
            matches, capped, timed_out = [], False, False
            scan_stats: dict = {}
            # Search is exact over each eligible policy-scoped file. A fixed
            # cumulative byte ceiling bounds broad repository scans.
            search_bytes_cap = max(
                16 * 1024 * 1024, cap * config.limits["max_search_results"]
            )
            try:
                for path, _blob, data in iter_tree_blobs(
                    change.repo,
                    commit,
                    max_file_bytes=cap,
                    max_total_bytes=search_bytes_cap,
                    path_filter=policy.matches,
                    deadline=deadline,
                    stats=scan_stats,
                ):
                    if deadline is not None and time.monotonic() >= deadline:
                        scan_stats["partial"] = True
                        scan_stats["limit_reason"] = "deadline"
                        break
                    try:
                        if b"\0" in data:
                            raise UnicodeError("binary NUL byte")
                        text = data.decode("utf-8")
                    except UnicodeError:
                        scan_stats["partial"] = True
                        scan_stats["skipped_files"] += 1
                        scan_stats["skipped_paths"].append(path)
                        continue
                    for number, line in enumerate(text.splitlines(), 1):
                        if deadline is not None and time.monotonic() >= deadline:
                            scan_stats["partial"] = True
                            scan_stats["limit_reason"] = "deadline"
                            timed_out = True
                            break
                        if literal in line:
                            match_at = line.find(literal)
                            excerpt_size = max(500, len(literal))
                            excerpt_start = max(
                                0,
                                min(
                                    match_at - (excerpt_size - len(literal)) // 2,
                                    max(0, len(line) - excerpt_size),
                                ),
                            )
                            excerpt_end = min(len(line), excerpt_start + excerpt_size)
                            excerpt = line[excerpt_start:excerpt_end]
                            matches.append(
                                {
                                    "id": digest(
                                        canonical([snapshot, path, number, literal])
                                    )[:16],
                                    "path": path,
                                    "line": number,
                                    "commit": commit,
                                    "content": excerpt,
                                    "column_range": [excerpt_start + 1, excerpt_end],
                                    "line_truncated": excerpt_start > 0
                                    or excerpt_end < len(line),
                                    "line_sha256": digest(line.encode("utf-8")),
                                    "precision": "source_exact",
                                }
                            )
                            if len(matches) >= config.limits["max_search_results"]:
                                capped = True
                                break
                    if (
                        capped
                        or timed_out
                        or scan_stats.get("limit_reason") == "deadline"
                    ):
                        break
            except TimeoutError:
                scan_stats["partial"] = True
                scan_stats["limit_reason"] = "deadline"
            except UnicodeError:
                scan_stats["partial"] = True
                scan_stats["skipped_files"] += 1
            # Search inventory is derived from the selected immutable tree,
            # not from the changed-path list; include unchanged policy files.
            result.update(
                status="partial" if scan_stats.get("partial") or capped else "ok",
                items=matches,
                coverage=(
                    "partial"
                    if scan_stats.get("partial") or capped
                    else "complete_for_declared_scope"
                ),
                skipped_files=scan_stats.get("skipped_files", 0),
                skipped_paths=scan_stats.get("skipped_paths", []),
                scanned_bytes=scan_stats.get("bytes_read", 0),
                warnings=(["search result cap reached"] if capped else [])
                + (
                    [scan_stats["limit_reason"]]
                    if scan_stats.get("limit_reason")
                    else []
                ),
            )
        elif kind in ("GET_CALLERS", "GET_CALLEES") and provider:
            relation = provider.relation(kind, f"{target['path']}:{target['symbol']}")
            result.update(
                status="partial",
                items=[
                    {"id": candidate.id, "content": relation, "precision": "heuristic"}
                ],
                coverage="partial",
            )
    except ComparisonError as exc:
        if kind in ("GET_CALLERS", "GET_CALLEES"):
            raise ProviderError(str(exc)) from exc
        result.update(status="partial", coverage="unknown", warnings=[str(exc)[:200]])
    except (UnicodeError, KeyError, ValueError) as exc:
        result.update(status="partial", coverage="unknown", warnings=[str(exc)[:200]])
    if len(canonical(result)) > cap:
        return {
            "candidate_id": candidate.id,
            "type": kind,
            "target": target,
            "status": "partial",
            "items": [],
            "coverage": "partial",
            "warnings": ["response exceeds evidence cap"],
        }
    return result
