"""Diff presentation and conservative finding identity for campaign consumers."""

from __future__ import annotations

from .config import Config
from .diff_chunking import DiffChunk
from .policy import Policy
from .util import canonical, digest


def _diffs(evidence: dict) -> list[dict]:
    if evidence.get("type") == "PRIOR_FINDING":
        return evidence["finding"].get("related_diff", [])
    if evidence.get("type") != "GET_DIFF_CHUNK":
        return []
    if "content" in evidence:
        return [evidence["content"]]
    return [
        item["content"]
        for item in evidence.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("content"), dict)
    ]


def _identity_content(value):
    """Ignore run/commit/offset identities while retaining actual source and scope."""
    if isinstance(value, dict):
        return {
            key: _identity_content(item)
            for key, item in sorted(value.items())
            if key
            not in {
                "id",
                "candidate_id",
                "chunk_id",
                "unit_id",
                "evidence_id",
                "commit",
                "start",
                "end",
                "ordinal",
                "raw_range",
                "selected_probability",
                "support_probability",
            }
        }
    if isinstance(value, list):
        return [_identity_content(item) for item in value]
    return value


def finding_context(
    policy: Policy,
    config: Config,
    chunk: DiffChunk | None,
    delivered: dict,
    support: dict,
) -> dict:
    related = {}
    for envelope in (
        *([chunk.envelope()] if chunk else []),
        *(diff for evidence in delivered.values() for diff in _diffs(evidence)),
    ):
        if any(policy.matches(path) for path in envelope.get("paths", [])):
            key = digest(canonical(_identity_content(envelope)))
            related[key] = envelope
    # Sort by content identity so acquisition order cannot change the identifier.
    diffs = [related[key] for key in sorted(related)]
    identity = {
        "policy_sha256": digest(policy.raw),
        "documents": {
            name: config.documents[name]["sha256"] for name in policy.data["documents"]
        },
        "related_diff": _identity_content(diffs),
        "support": _identity_content(support),
        "observed_evidence": sorted(
            {digest(canonical(_identity_content(item))) for item in delivered.values()}
        ),
    }
    return {
        "finding_id": "finding-" + digest(canonical(identity)),
        "policy_statement": policy.data["statement"],
        "related_diff": diffs,
    }
