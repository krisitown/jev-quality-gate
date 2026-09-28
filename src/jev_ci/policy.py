"""Strict, frozen YAML policy packs."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent, ScalarEvent

from .config import Config
from .errors import ConfigError
from .util import canonical, digest, fields, positive_int, ratio

ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
REQUESTS = {
    "GET_DIFF_CHUNK",
    "GET_FILE",
    "SEARCH_CODE",
    "GET_DOCUMENT",
    "GET_SYMBOL",
    "GET_CALLERS",
    "GET_CALLEES",
    "GET_IMPLEMENTATIONS",
    "GET_TESTS",
    "GET_DEPENDENCY_NEIGHBORHOOD",
}


def parse_policy_yaml(raw: bytes) -> dict:
    loader = YAML(typ="safe", pure=True)
    loader.version = (1, 2)
    loader.allow_duplicate_keys = False
    source = raw.decode("utf-8")
    for event in loader.parse(source):
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML aliases and anchors are prohibited")
        if isinstance(event, ScalarEvent) and (
            event.value == "<<" or (event.tag and event.tag.startswith("!"))
        ):
            raise ValueError("YAML merge keys and custom tags are prohibited")
    value = loader.load(source)
    if not isinstance(value, dict):
        raise ValueError("policy YAML must be one mapping")
    return value


@dataclass(frozen=True)
class Policy:
    path: str
    raw: bytes
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    def matches(self, path: str) -> bool:
        scope = self.data["scope"]
        return any(
            fnmatch.fnmatchcase(path, pattern) for pattern in scope["include"]
        ) and not any(
            fnmatch.fnmatchcase(path, pattern) for pattern in scope["exclude"]
        )


@dataclass(frozen=True)
class PolicyPack:
    policies: tuple[Policy, ...]
    manifest: dict[str, Any]


def _strings(value: object, location: str, *, nonempty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(x, str) or not x.strip() for x in value)
    ):
        raise ValueError(f"{location} must be a list of nonempty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{location} has duplicates")
    return value


def _text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{location} must be 1–4096 characters")
    return value


def validate_policy(data: object, config: Config) -> dict:
    data = fields(
        data,
        {
            "schema_version",
            "id",
            "version",
            "statement",
            "question",
            "scope",
            "interpretation",
            "outcomes",
            "documents",
            "aggregation",
            "discovery",
            "evidence",
            "confidence",
            "feedback",
            "ci",
        },
        {
            "schema_version",
            "id",
            "version",
            "statement",
            "question",
            "scope",
            "interpretation",
            "outcomes",
            "documents",
            "aggregation",
            "discovery",
            "evidence",
            "confidence",
            "feedback",
            "ci",
        },
        "policy",
    )
    if (
        data["schema_version"] != "jev.policy/0.2"
        or not isinstance(data["id"], str)
        or not ID.fullmatch(data["id"])
    ):
        raise ValueError("unsupported policy schema or invalid ID")
    for key in ("version", "statement", "question"):
        _text(data[key], key)
    scope = fields(
        data["scope"],
        {"include", "exclude", "change_kind"},
        {"include", "exclude", "change_kind"},
        "scope",
    )
    if scope["change_kind"] != "introduced_or_worsened":
        raise ValueError("unsupported change_kind")
    for key in ("include", "exclude"):
        for pattern in _strings(scope[key], f"scope.{key}", nonempty=key == "include"):
            path = Path(pattern)
            if (
                path.is_absolute()
                or ".." in path.parts
                or pattern.startswith(("~", "!"))
                or "\\" in pattern
            ):
                raise ValueError("unsafe scope pattern")
    interpretation = fields(
        data["interpretation"],
        {"definitions", "exceptions", "ambiguity"},
        {"definitions", "exceptions", "ambiguity"},
        "interpretation",
    )
    for key in interpretation:
        _strings(interpretation[key], f"interpretation.{key}")
    if data["outcomes"] != ["compliant", "violation", "uncertain"]:
        raise ValueError("outcomes must be compliant, violation, uncertain")
    for name in _strings(data["documents"], "documents"):
        if name not in config.documents:
            raise ValueError(f"missing trusted document binding: {name}")
    aggregation = fields(
        data["aggregation"], {"mode", "justification"}, {"mode"}, "aggregation"
    )
    if aggregation["mode"] not in ("requires_reconciliation", "independent_chunks"):
        raise ValueError("unsupported aggregation mode")
    if aggregation["mode"] == "independent_chunks":
        _text(aggregation.get("justification"), "aggregation.justification")
    elif "justification" in aggregation:
        _text(aggregation["justification"], "aggregation.justification")
    discovery = fields(
        data["discovery"], {"search_terms"}, {"search_terms"}, "discovery"
    )
    for term in _strings(discovery["search_terms"], "discovery.search_terms"):
        if len(term.encode()) > 128 or "\n" in term:
            raise ValueError("search term exceeds limit or contains newline")
    evidence = fields(
        data["evidence"],
        {
            "allowed_requests",
            "max_rounds",
            "max_requests_per_round",
            "max_input_tokens",
            "max_evidence_bytes",
        },
        {
            "allowed_requests",
            "max_rounds",
            "max_requests_per_round",
            "max_input_tokens",
            "max_evidence_bytes",
        },
        "evidence",
    )
    allowed = _strings(
        evidence["allowed_requests"], "evidence.allowed_requests", nonempty=True
    )
    if not set(allowed) <= REQUESTS:
        raise ValueError("unknown evidence request")
    for key in (
        "max_rounds",
        "max_requests_per_round",
        "max_input_tokens",
        "max_evidence_bytes",
    ):
        positive_int(evidence[key], f"evidence.{key}")
    if (
        evidence["max_rounds"] > config.limits["max_rounds"]
        or evidence["max_evidence_bytes"] > config.limits["max_evidence_bytes"]
    ):
        raise ValueError("policy relaxes root evidence limits")
    if evidence["max_requests_per_round"] > 3:
        raise ValueError("at most three requests per round")
    confidence = fields(
        data["confidence"],
        {
            "metric",
            "compliant_min",
            "violation_min",
            "request_selection_min",
            "support_min",
            "calibration_id",
        },
        {
            "metric",
            "compliant_min",
            "violation_min",
            "request_selection_min",
            "support_min",
            "calibration_id",
        },
        "confidence",
    )
    if confidence["metric"] != "selected_probability":
        raise ValueError("unsupported confidence metric")
    for key in (
        "compliant_min",
        "violation_min",
        "request_selection_min",
        "support_min",
    ):
        ratio(confidence[key], f"confidence.{key}", nullable=True)
        if config.mode == "gate" and confidence[key] is None:
            raise ValueError("gate policy requires calibrated thresholds")
    if config.mode == "gate" and not confidence["calibration_id"]:
        raise ValueError("gate policy requires calibration_id")
    if confidence["calibration_id"] is not None:
        _text(confidence["calibration_id"], "confidence.calibration_id")
    feedback = fields(
        data["feedback"],
        {"violation", "repair_guidance"},
        {"violation", "repair_guidance"},
        "feedback",
    )
    for key in feedback:
        _text(feedback[key], f"feedback.{key}")
    ci = fields(
        data["ci"],
        {"severity", "compliant", "violation", "uncertain"},
        {"severity", "compliant", "violation", "uncertain"},
        "ci",
    )
    if (
        ci["severity"] not in ("info", "warning", "error")
        or ci["compliant"] != "report"
        or ci["violation"] not in ("report", "warn", "block")
        or ci["uncertain"] not in ("report", "warn", "block")
    ):
        raise ValueError("invalid CI action")
    if config.mode == "calibration" and (
        ci["violation"] == "block" or ci["uncertain"] == "block"
    ):
        raise ValueError("calibration policies cannot block")
    return data


def load_policies(root: Path, config: Config) -> PolicyPack:
    try:
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("policy root is not a directory")
        paths = sorted(
            (p for p in root.rglob("*") if p.suffix.lower() in (".yaml", ".yml")),
            key=lambda p: p.relative_to(root).as_posix(),
        )
        if not paths or len(paths) > config.limits["max_policies"]:
            raise ValueError("policy folder is empty or exceeds policy count")
        result, entries, total, ids = [], [], 0, set()
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("policy symlink escapes or redirects")
            raw = path.read_bytes()
            total += len(raw)
            if (
                len(raw) > config.limits["max_policy_bytes"]
                or total > config.limits["max_policy_folder_bytes"]
            ):
                raise ValueError("policy bytes exceed configured limit")
            data = validate_policy(parse_policy_yaml(raw), config)
            if data["id"] in ids:
                raise ValueError(f"duplicate policy ID: {data['id']}")
            ids.add(data["id"])
            rel = path.relative_to(root).as_posix()
            result.append(Policy(rel, raw, data))
            entries.append(
                {
                    "path": rel,
                    "id": data["id"],
                    "raw_sha256": digest(raw),
                    "normalized_sha256": digest(canonical(data)),
                }
            )
        result.sort(key=lambda policy: policy.id)
        return PolicyPack(
            tuple(result),
            {
                "schema_version": "jev.policy-pack/0.1",
                "files": entries,
                "sha256": digest(canonical(entries)),
            },
        )
    except (OSError, UnicodeError, ValueError, TypeError, YAMLError) as exc:
        raise ConfigError(f"invalid policy folder: {exc}") from exc
