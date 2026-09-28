"""Trusted root configuration, independent of candidate Git content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .util import digest, fields, positive_int, strict_json

SCHEMA = "jev.config/0.2"
ENDPOINT = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"


@dataclass(frozen=True)
class Config:
    path: Path
    raw: bytes
    data: dict[str, Any]
    documents: dict[str, dict[str, Any]]

    @property
    def hash(self) -> str:
        return digest(self.raw)

    @property
    def mode(self) -> str:
        return self.data["mode"]

    @property
    def diff(self) -> dict:
        return self.data["diff"]

    @property
    def limits(self) -> dict:
        return self.data["limits"]

    @property
    def inference(self) -> dict:
        return self.data["inference"]


def load_config(path: Path) -> Config:
    try:
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError("config exceeds 1 MiB")
        data = fields(
            strict_json(raw),
            {
                "schema_version",
                "mode",
                "control_bundle",
                "document_bindings",
                "inference",
                "providers",
                "diff",
                "limits",
                "ci",
                "policy_dir",
            },
            {
                "schema_version",
                "mode",
                "control_bundle",
                "document_bindings",
                "inference",
                "providers",
                "diff",
                "limits",
                "ci",
            },
            "config",
        )
        if data["schema_version"] != SCHEMA or data["mode"] not in (
            "calibration",
            "gate",
        ):
            raise ValueError("unsupported config schema or mode")
        bundle = fields(
            data["control_bundle"],
            {"id", "root", "revision"},
            {"id", "root", "revision"},
            "control_bundle",
        )
        root = Path(bundle["root"])
        if not root.is_absolute():
            root = path.resolve().parent / root
        if not root.is_dir():
            raise ValueError("control_bundle.root must be an existing directory")
        root = root.resolve()
        if (
            not isinstance(bundle["id"], str)
            or not bundle["id"]
            or not isinstance(bundle["revision"], str)
            or not bundle["revision"]
        ):
            raise ValueError("control bundle identity and revision are required")
        bindings = data["document_bindings"]
        if not isinstance(bindings, list):
            raise ValueError("document_bindings must be a list")
        documents = {}
        for item in bindings:
            item = fields(
                item,
                {"id", "path", "sha256", "authority"},
                {"id", "path", "sha256", "authority"},
                "document binding",
            )
            name = item["id"]
            if not isinstance(name, str) or not name or name in documents:
                raise ValueError("invalid or duplicate document ID")
            rel = Path(item["path"])
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise ValueError("document path must stay under control root")
            declared = root / rel
            if any(
                part.is_symlink()
                for part in (declared, *declared.parents)
                if part == root or part.is_relative_to(root)
            ):
                raise ValueError(f"document {name} uses a symlink")
            file = declared.resolve()
            if not file.is_file() or not file.is_relative_to(root):
                raise ValueError(f"document {name} is missing or escapes control root")
            content = file.read_bytes()
            if len(content) > 128 * 1024 or digest(content) != item["sha256"]:
                raise ValueError(f"document {name} exceeds limit or hash mismatch")
            if item["authority"] != "trusted":
                raise ValueError("document binding must be trusted")
            documents[name] = {**item, "content": content.decode("utf-8")}
        inference = fields(
            data["inference"],
            {
                "adapter",
                "model",
                "endpoint",
                "credential_env",
                "timeout_seconds",
                "max_request_bytes",
                "max_response_bytes",
                "max_questions",
            },
            {
                "adapter",
                "model",
                "endpoint",
                "credential_env",
                "timeout_seconds",
                "max_request_bytes",
                "max_response_bytes",
                "max_questions",
            },
            "inference",
        )
        if (
            inference["adapter"],
            inference["model"],
            inference["endpoint"],
            inference["credential_env"],
        ) != ("vercel-typesafe", "typesafe-ai/jev", ENDPOINT, "AI_GATEWAY_API_KEY"):
            raise ValueError(
                "unsupported inference adapter, model, endpoint, or credential variable"
            )
        for key in (
            "timeout_seconds",
            "max_request_bytes",
            "max_response_bytes",
            "max_questions",
        ):
            positive_int(inference[key], f"inference.{key}")
        providers = fields(
            data["providers"], {"enabled", "ripwire"}, {"enabled"}, "providers"
        )
        if providers["enabled"] not in (["git-exact"], ["git-exact", "ripwire"]):
            raise ValueError(
                "providers.enabled must be git-exact, optionally followed by ripwire"
            )
        if "ripwire" in providers["enabled"]:
            ripwire = fields(
                providers.get("ripwire"),
                {
                    "binary",
                    "sha256",
                    "version",
                    "timeout_seconds",
                    "max_output_bytes",
                    "max_snapshot_bytes",
                    "max_symbols",
                },
                {
                    "binary",
                    "sha256",
                    "version",
                    "timeout_seconds",
                    "max_output_bytes",
                    "max_snapshot_bytes",
                    "max_symbols",
                },
                "providers.ripwire",
            )
            binary = Path(ripwire["binary"])
            if (
                not binary.is_absolute()
                or not binary.is_file()
                or digest(binary.read_bytes()) != ripwire["sha256"]
            ):
                raise ValueError("Ripwire binary missing or checksum mismatch")
            if ripwire["version"] != "0.6.5":
                raise ValueError("Ripwire adapter was validated only against 0.6.5")
            for key in (
                "timeout_seconds",
                "max_output_bytes",
                "max_snapshot_bytes",
                "max_symbols",
            ):
                positive_int(ripwire[key], f"providers.ripwire.{key}")
        elif "ripwire" in providers:
            raise ValueError("ripwire settings supplied but provider not enabled")
        diff = fields(
            data["diff"],
            {"strategy", "max_chunk_bytes", "max_total_diff_bytes", "max_chunks"},
            {"strategy", "max_chunk_bytes", "max_total_diff_bytes", "max_chunks"},
            "diff",
        )
        if diff["strategy"] != "bounded-sequential-v1":
            raise ValueError("unsupported diff strategy")
        for key in ("max_chunk_bytes", "max_total_diff_bytes", "max_chunks"):
            positive_int(diff[key], f"diff.{key}")
        if diff["max_chunk_bytes"] > diff["max_total_diff_bytes"]:
            raise ValueError("chunk cap cannot exceed total diff cap")
        limits = fields(
            data["limits"],
            {
                "max_policies",
                "max_policy_bytes",
                "max_policy_folder_bytes",
                "max_calls",
                "max_seconds",
                "max_rounds",
                "max_candidates",
                "max_evidence_bytes",
                "max_search_results",
                "max_input_bytes",
            },
            {
                "max_policies",
                "max_policy_bytes",
                "max_policy_folder_bytes",
                "max_calls",
                "max_seconds",
                "max_rounds",
                "max_candidates",
                "max_evidence_bytes",
                "max_search_results",
                "max_input_bytes",
            },
            "limits",
        )
        for key, value in limits.items():
            positive_int(value, f"limits.{key}")
        ci = fields(
            data["ci"],
            {"incomplete", "operational_error"},
            {"incomplete", "operational_error"},
            "ci",
        )
        if ci != {"incomplete": "report", "operational_error": "error"} and ci != {
            "incomplete": "block",
            "operational_error": "error",
        }:
            raise ValueError(
                "ci.incomplete must report or block; operational_error must error"
            )
        if "policy_dir" in data and not isinstance(data["policy_dir"], str):
            raise ValueError("policy_dir must be a path string")
        return Config(path.resolve(), raw, data, documents)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ConfigError(f"invalid config: {exc}") from exc
