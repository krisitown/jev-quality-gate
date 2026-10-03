"""Sequential, durable evaluation of all applicable branch changes."""

from __future__ import annotations

import os
import json
import time
from contextlib import nullcontext
from pathlib import Path

from dotenv import dotenv_values

from . import __version__
from .aggregation import aggregate, run_status
from .config import Config, load_config
from .diff_chunking import chunk_diff
from .errors import ConfigError, InferenceError, JevCIError, ProviderError
from .evaluator import Evaluator
from .git import compare
from .html_report import render_html
from .inference import Gateway
from .policy import load_policies
from .providers import RipwireProvider
from .protocol import run_unit
from .reporting import render_markdown
from .trace import Pack
from .util import canonical, digest


def policy_path(config: Config, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if "policy_dir" not in config.data:
        raise ConfigError("--policies or config.policy_dir is required")
    path = Path(config.data["policy_dir"])
    return path if path.is_absolute() else config.path.parent / path


def validate(config_path: Path, policies_path: Path | None) -> dict:
    config = load_config(config_path)
    pack = load_policies(policy_path(config, policies_path), config)
    return {
        "schema_version": "jev.validation/0.1",
        "status": "valid",
        "mode": config.mode,
        "config_sha256": config.hash,
        "policy_pack_sha256": pack.manifest["sha256"],
        "policies": [p.id for p in pack.policies],
        "providers": config.data["providers"]["enabled"],
    }


def _credential(config: Config, env_file: Path | None) -> str:
    name = config.inference["credential_env"]
    if name in os.environ:
        return os.environ[name]
    if env_file is None:
        return ""
    if not env_file.is_file() or env_file.is_symlink():
        raise ConfigError("--env-file must be an existing regular file")
    values = dotenv_values(env_file)
    return values.get(name) or ""


def evaluate(
    repo: Path,
    source: str,
    target: str,
    config_path: Path,
    policies_path: Path | None,
    output: Path,
    env_file: Path | None = None,
    *,
    transport=None,
    evaluator: Evaluator | None = None,
) -> dict:
    trace = Pack(output)
    html_chunks = []
    html_units = []
    summary = {
        "schema_version": "jev.summary/0.1",
        "run_id": trace.run_id,
        "status": "error",
        "exit_code": 2,
        "output": str(output),
        "policies": [],
        "errors": [],
    }
    try:
        config = load_config(config_path)
        deadline = time.monotonic() + config.limits["max_seconds"]
        policy_pack = load_policies(policy_path(config, policies_path), config)
        trace.write(
            "manifest.json",
            {
                "schema_version": "jev.pack/0.2",
                "run_id": trace.run_id,
                "tool_version": __version__,
                "protocol_version": "jev.protocol/0.4",
                "config_sha256": config.hash,
                "policy_pack_sha256": policy_pack.manifest["sha256"],
                "mode": config.mode,
                "providers": config.data["providers"],
                "limits": config.limits,
                "protocol_replay": "self_contained",
                "retrieval_replay": "requires_original_git_objects_and_pinned_provider",
            },
        )
        trace.blob(config.raw)
        for name, document in config.documents.items():
            trace.blob(document["content"].encode())
        for policy in policy_pack.policies:
            trace.blob(policy.raw)
        trace.write("policies/manifest.json", policy_pack.manifest)
        change = compare(
            repo, source, target, config.diff["max_total_diff_bytes"], deadline=deadline
        )
        trace.event("comparison_resolved", change.descriptor())
        trace.blob(change.raw_diff)
        chunks = chunk_diff(change, config.diff)
        html_chunks = list(chunks.summary["chunks"])
        trace.write("chunks/manifest.json", chunks.summary)
        trace.event(
            "chunks_created",
            {
                "status": chunks.status,
                "reason": chunks.reason,
                "count": len(chunks.chunks),
            },
        )
        manifest = json.loads((trace.path / "manifest.json").read_text())
        manifest.update(
            comparison=change.descriptor(),
            chunk_manifest_sha256=digest(canonical(chunks.summary)),
            ordered_units=[],
        )
        schedule: dict[str, list] = {}
        for policy in policy_pack.policies:
            applicable = [
                chunk
                for chunk in chunks.chunks
                if any(policy.matches(path) for path in chunk.paths)
            ]
            schedule[policy.id] = applicable
        for chunk in chunks.chunks:
            for policy in policy_pack.policies:
                if chunk in schedule[policy.id]:
                    manifest["ordered_units"].append(
                        {"policy_id": policy.id, "chunk_id": chunk.id, "kind": "chunk"}
                    )
        for policy in policy_pack.policies:
            if (
                schedule[policy.id]
                and policy.data["aggregation"]["mode"] == "requires_reconciliation"
            ):
                manifest["ordered_units"].append(
                    {"policy_id": policy.id, "chunk_id": None, "kind": "reconciliation"}
                )
        trace.write("manifest.json", manifest)
        minimum = len(manifest["ordered_units"])
        insufficient = minimum > config.limits["max_calls"]
        if insufficient:
            trace.event(
                "budget_updated",
                {
                    "minimum_calls": minimum,
                    "available_calls": config.limits["max_calls"],
                    "status": "insufficient_preflight",
                },
            )
        if chunks.status != "complete":
            trace.event(
                "scope_resolved", {"status": "incomplete", "reason": chunks.reason}
            )
        elif insufficient:
            trace.event(
                "scope_resolved",
                {"status": "incomplete", "reason": "insufficient_run_calls"},
            )
        else:
            trace.event(
                "scope_resolved", {"status": "complete", "scheduled_units": minimum}
            )
        active = bool(minimum) and chunks.status == "complete" and not insufficient
        if not active:
            for unit in manifest["ordered_units"]:
                trace.event(
                    "unit_skipped",
                    {**unit, "reason": chunks.reason or "insufficient_run_calls"},
                    policy_id=unit["policy_id"],
                    chunk_id=unit["chunk_id"],
                )
        key = _credential(config, env_file) if active and evaluator is None else ""
        gateway = (
            (
                evaluator
                if evaluator is not None
                else Gateway(config.inference, key, transport=transport)
            )
            if active
            else None
        )
        manifest["evaluator"] = (
            gateway.identity
            if gateway
            else {
                "adapter": config.inference["adapter"],
                "model": config.inference["model"],
            }
        )
        trace.write("manifest.json", manifest)
        provider_ctx = (
            RipwireProvider(
                change, config.data["providers"]["ripwire"], deadline=deadline
            )
            if active and "ripwire" in config.data["providers"]["enabled"]
            else nullcontext(None)
        )
        budget = {
            "remaining": config.limits["max_calls"],
            "reserved": minimum - 1,
            "deadline": deadline,
            "native_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "input_reports": 0,
                "output_reports": 0,
                "cost_usd": "0",
                "cost_reports": 0,
            },
        }
        results: dict[str, list] = {p.id: [] for p in policy_pack.policies}
        reconciliations = {}
        errors = []
        fatal = False
        with provider_ctx as provider:
            if provider is not None:
                trace.event(
                    "provider_prepared",
                    {
                        "descriptor": provider.describe(),
                        "map_blob": trace.blob(provider.last_raw),
                        "map": provider.map,
                    },
                )
            for chunk in chunks.chunks:
                for policy in policy_pack.policies:
                    if chunk not in schedule[policy.id] or not active:
                        continue
                    if fatal or time.monotonic() >= deadline:
                        trace.event(
                            "unit_skipped",
                            {
                                "kind": "chunk",
                                "reason": "operational_error"
                                if fatal
                                else "run_deadline",
                            },
                            policy_id=policy.id,
                            chunk_id=chunk.id,
                        )
                        continue
                    budget["reserved"] = max(0, budget["reserved"])
                    try:
                        result = run_unit(
                            policy,
                            chunk,
                            change,
                            chunks,
                            config,
                            provider,
                            gateway,
                            trace,
                            budget,
                        )
                    except (InferenceError, ProviderError) as exc:
                        reason = (
                            "run_call_budget"
                            if "budget" in str(exc)
                            else "provider_error"
                            if isinstance(exc, ProviderError)
                            else "inference_error"
                        )
                        result = {
                            "id": digest(canonical([policy.id, chunk.id])),
                            "policy_id": policy.id,
                            "unit_kind": "chunk",
                            "chunk_id": chunk.id,
                            "outcome": "uncertain",
                            "reason": reason,
                            "finding": None,
                            "calls": 0,
                            "rounds": [],
                        }
                        trace.event(
                            "inference_error",
                            {"reason": reason, "error": str(exc)[:200]},
                            result["id"],
                            policy.id,
                            chunk.id,
                        )
                        trace.event(
                            "evaluation_finished",
                            {"outcome": "uncertain", "reason": reason},
                            result["id"],
                            policy.id,
                            chunk.id,
                        )
                        if reason != "run_call_budget":
                            errors.append(str(exc)[:200])
                            fatal = True
                    if result.get("operational_error"):
                        errors.append(result["operational_error"])
                        fatal = True
                    results[policy.id].append(result)
                    html_units.append(result)
                    trace.write(f"evaluations/{result['id']}/result.json", result)
                    budget["reserved"] = max(0, budget["reserved"] - 1)
            for policy in policy_pack.policies:
                if (
                    not active
                    or not schedule[policy.id]
                    or policy.data["aggregation"]["mode"] != "requires_reconciliation"
                ):
                    continue
                if fatal or time.monotonic() >= deadline:
                    trace.event(
                        "unit_skipped",
                        {
                            "kind": "reconciliation",
                            "reason": "operational_error" if fatal else "run_deadline",
                        },
                        policy_id=policy.id,
                    )
                    continue
                trace.event(
                    "reconciliation_started",
                    {"policy_id": policy.id},
                    policy_id=policy.id,
                )
                try:
                    reconciliation = run_unit(
                        policy,
                        None,
                        change,
                        chunks,
                        config,
                        provider,
                        gateway,
                        trace,
                        budget,
                        prior=results[policy.id],
                    )
                except (InferenceError, ProviderError) as exc:
                    reason = (
                        "run_call_budget"
                        if "budget" in str(exc)
                        else "provider_error"
                        if isinstance(exc, ProviderError)
                        else "inference_error"
                    )
                    reconciliation = {
                        "id": digest(canonical([policy.id, "reconciliation"])),
                        "policy_id": policy.id,
                        "unit_kind": "reconciliation",
                        "chunk_id": None,
                        "outcome": "uncertain",
                        "reason": reason,
                        "finding": None,
                        "calls": 0,
                        "rounds": [],
                    }
                    trace.event(
                        "inference_error",
                        {"reason": reason, "error": str(exc)[:200]},
                        reconciliation["id"],
                        policy.id,
                    )
                    trace.event(
                        "evaluation_finished",
                        {"outcome": "uncertain", "reason": reason},
                        reconciliation["id"],
                        policy.id,
                    )
                    if reason != "run_call_budget":
                        errors.append(str(exc)[:200])
                        fatal = True
                if reconciliation.get("operational_error"):
                    errors.append(reconciliation["operational_error"])
                    fatal = True
                reconciliations[policy.id] = reconciliation
                html_units.append(reconciliation)
                trace.write(
                    f"evaluations/{reconciliation['id']}/result.json", reconciliation
                )
                budget["reserved"] = max(0, budget["reserved"] - 1)
        aggregates = []
        for policy in policy_pack.policies:
            expected = [chunk.id for chunk in schedule[policy.id]]
            unsupported = any(policy.matches(path) for path in change.unsupported_paths)
            item = aggregate(
                policy,
                results[policy.id],
                reconciliations.get(policy.id),
                expected,
                unsupported,
                chunks.status != "complete" or insufficient,
            )
            if (
                item["outcome"] == "uncertain"
                and config.data["ci"]["incomplete"] == "block"
            ):
                item["action"] = "block"
            aggregates.append(item)
            trace.write(f"policies/{policy.id}/aggregate.json", item)
            trace.event(
                "policy_aggregated",
                {
                    "policy_id": policy.id,
                    "outcome": item["outcome"],
                    "action": item["action"],
                    "unvisited": item["unvisited_chunks"],
                },
                policy_id=policy.id,
            )
            trace.event(
                "ci_action",
                {
                    "policy_id": policy.id,
                    "action": item["action"],
                    "outcome": item["outcome"],
                },
                policy_id=policy.id,
            )
        status, code = run_status(aggregates, errors)
        if config.mode == "calibration" and status == "blocked":
            status, code = "completed_with_findings", 0
        feedback = {
            "schema_version": "jev.feedback/0.2",
            "findings": [
                finding for item in aggregates for finding in item["findings"]
            ],
            "uncertain": [
                {
                    "policy_id": item["policy_id"],
                    "reason": item["reason"],
                    "unvisited_chunks": item["unvisited_chunks"],
                }
                for item in aggregates
                if item["outcome"] == "uncertain"
            ],
        }
        trace.write("feedback.json", feedback)
        summary.update(
            status=status,
            exit_code=code,
            policies=aggregates,
            errors=errors,
            comparison=change.descriptor(),
            diagnostics=[
                {
                    "policy_id": policy.id,
                    "unit_id": unit["id"],
                    "unit_kind": unit["unit_kind"],
                    "chunk_id": unit["chunk_id"],
                    "outcome": unit["outcome"],
                    "reason": unit["reason"],
                    "calls": unit["calls"],
                }
                for policy in policy_pack.policies
                for unit in [
                    *results[policy.id],
                    *(
                        [reconciliations[policy.id]]
                        if policy.id in reconciliations
                        else []
                    ),
                ]
                if unit["outcome"] != "compliant"
            ],
            coverage={
                "chunk_status": chunks.status,
                "chunk_reason": chunks.reason,
                "chunks": len(chunks.chunks),
                "calls_remaining": budget["remaining"],
                "calls_used": config.limits["max_calls"] - budget["remaining"],
                "native_usage": {
                    **budget["native_usage"],
                    "input_tokens": budget["native_usage"]["input_tokens"]
                    if budget["native_usage"]["input_reports"]
                    else None,
                    "output_tokens": budget["native_usage"]["output_tokens"]
                    if budget["native_usage"]["output_reports"]
                    else None,
                    "cost_usd": budget["native_usage"]["cost_usd"]
                    if budget["native_usage"]["cost_reports"]
                    else None,
                },
            },
        )
    except (JevCIError, ValueError, OSError) as exc:
        summary["errors"].append(str(exc)[:300])
        trace.event("run_error", {"error": str(exc)[:300]})
    trace.write_text("report.md", render_markdown(summary))
    trace.write_text(
        "report.html", render_html(summary, chunks=html_chunks, units=html_units)
    )
    trace.finish(summary)
    return summary
