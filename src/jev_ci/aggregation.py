"""Coverage-first deterministic outcomes and CI actions."""

from __future__ import annotations

from .policy import Policy
from .util import canonical, digest


def aggregate(
    policy: Policy,
    units: list[dict],
    reconciliation: dict | None,
    expected_chunks: list[str],
    unsupported: bool,
    incomplete: bool = False,
) -> dict:
    seen = {unit["chunk_id"] for unit in units if unit["unit_kind"] == "chunk"}
    unfinished = [chunk_id for chunk_id in expected_chunks if chunk_id not in seen]
    findings = []
    matched = set()
    for unit in [*units, *([reconciliation] if reconciliation else [])]:
        finding = unit.get("finding")
        if finding:
            key = digest(
                canonical([policy.id, finding["message"], finding["evidence_id"]])
            )
            if key not in matched:
                findings.append(finding)
                matched.add(key)
    conflicts = []
    if (
        reconciliation
        and reconciliation["outcome"] == "compliant"
        and any(unit["outcome"] == "violation" for unit in units)
    ):
        conflicts.append("reconciliation_disagrees_with_supported_chunk_violation")
    if not expected_chunks and not unsupported and not incomplete:
        outcome, reason = "not_applicable", None
    elif conflicts:
        outcome, reason = "uncertain", "disputed_finding"
    elif findings:
        outcome, reason = "violation", None
    elif (
        unfinished
        or unsupported
        or incomplete
        or any(unit["outcome"] != "compliant" for unit in units)
        or (
            policy.data["aggregation"]["mode"] == "requires_reconciliation"
            and (reconciliation is None or reconciliation["outcome"] != "compliant")
        )
    ):
        outcome, reason = "uncertain", "incomplete_coverage"
    else:
        outcome, reason = "compliant", None
    action = policy.data["ci"].get(outcome, "report")
    return {
        "schema_version": "jev.aggregate/0.1",
        "policy_id": policy.id,
        "outcome": outcome,
        "reason": reason,
        "action": action,
        "confidence": None,
        "expected_chunks": expected_chunks,
        "completed_units": [unit["id"] for unit in units],
        "unvisited_chunks": unfinished,
        "unsupported_content": unsupported,
        "incomplete_coverage": incomplete,
        "reconciliation_id": reconciliation["id"] if reconciliation else None,
        "conflicts": conflicts,
        "findings": findings,
    }


def run_status(aggregates: list[dict], errors: list[str]) -> tuple[str, int]:
    if errors:
        return "error", 2
    if any(
        item["action"] == "block" and item["outcome"] in ("violation", "uncertain")
        for item in aggregates
    ):
        return "blocked", 1
    if any(item["outcome"] in ("violation", "uncertain") for item in aggregates):
        return "completed_with_findings", 0
    return "completed", 0
