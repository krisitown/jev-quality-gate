"""Concrete, immutable evidence menus and bounded retrieval."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Config
from .diff_chunking import ChunkManifest, DiffChunk
from .errors import ComparisonError, ProviderError
from .git import Comparison, _git, show_file
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
) -> tuple[list[Candidate], dict]:
    proposed: list[tuple[str, dict, str]] = []

    def add(kind: str, target: dict, purpose: str):
        if kind in policy.data["evidence"]["allowed_requests"]:
            proposed.append((kind, target, purpose))

    relevant = [path for path in change.paths if policy.matches(path)]
    head_paths = _head_paths(str(change.repo), change.source)
    for path in relevant:
        snapshot = "base" if path not in head_paths else "head"
        add(
            "GET_FILE",
            {"path": path, "snapshot": snapshot},
            f"Read committed {snapshot} file containing the change",
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
                "Inspect another applicable change chunk",
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
    items = list(dedup.values())
    maximum = config.limits["max_candidates"]
    shown = items[:maximum]
    return shown, {
        "total": len(items),
        "shown": len(shown),
        "omitted": len(items) - len(shown),
        "sha256": digest(canonical([x.public() for x in shown])),
        "provider_symbol_map": provider_coverage,
    }


@lru_cache(maxsize=8)
def _head_paths(repo: str, source: str) -> frozenset[str]:
    raw = _git(
        Path(repo),
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        source,
        max_bytes=16 * 1024 * 1024,
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
                content = show_file(change, target["snapshot"], path, cap).decode(
                    "utf-8"
                )
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
            names = _git(
                change.repo,
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                commit,
                max_bytes=16 * 1024 * 1024,
            ).split(b"\0")
            matches, skipped, capped = [], 0, False
            for name in names:
                if not name:
                    continue
                path = name.decode("utf-8", "replace")
                if not policy.matches(path):
                    continue
                try:
                    data = show_file(change, snapshot, path, cap)
                    text = data.decode("utf-8")
                except (ComparisonError, UnicodeError):
                    skipped += 1
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if literal in line:
                        matches.append(
                            {
                                "id": digest(
                                    canonical([snapshot, path, number, literal])
                                )[:16],
                                "path": path,
                                "line": number,
                                "commit": commit,
                                "content": line[:500],
                                "precision": "source_exact",
                            }
                        )
                        if len(matches) >= config.limits["max_search_results"]:
                            capped = True
                            break
                if capped:
                    break
            result.update(
                status="partial" if skipped or capped else "ok",
                items=matches,
                coverage="partial"
                if skipped or capped
                else "complete_for_declared_scope",
                skipped_files=skipped,
                warnings=["search result cap reached"] if capped else [],
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
