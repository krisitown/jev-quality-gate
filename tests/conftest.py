from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from jev_ci.config import ENDPOINT


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def project(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.org")
    (repo / "src").mkdir()
    (repo / "src" / "Service.java").write_text(
        "class Service { int calculate(int x) { return x; } }\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "feature")
    (repo / "src" / "Service.java").write_text(
        "class Service { int calculate(int x) { return x + 1; } int handle() { return calculate(4); } }\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feature")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    (repo / "README.md").write_text("target advanced\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "target advances")
    control = tmp_path / "control"
    control.mkdir()
    doc = b"Service business decisions are owned by Service.\n"
    (control / "architecture.md").write_bytes(doc)
    policies = tmp_path / "policies"
    policies.mkdir()
    policy = {
        "schema_version": "jev.policy/0.2",
        "id": "business-decision-placement",
        "version": "0.2.0-draft",
        "statement": "Business decisions belong in Service.",
        "question": "Does this change move a business decision out of Service?",
        "scope": {
            "include": ["src/**"],
            "exclude": [],
            "change_kind": "introduced_or_worsened",
        },
        "interpretation": {
            "definitions": ["A business decision chooses behavior."],
            "exceptions": [],
            "ambiguity": ["Ownership is not documented."],
        },
        "outcomes": ["compliant", "violation", "uncertain"],
        "documents": ["architecture"],
        "aggregation": {"mode": "requires_reconciliation"},
        "discovery": {"search_terms": ["calculate"]},
        "evidence": {
            "allowed_requests": [
                "GET_DIFF_CHUNK",
                "GET_FILE",
                "SEARCH_CODE",
                "GET_DOCUMENT",
                "GET_CALLERS",
                "GET_CALLEES",
            ],
            "max_rounds": 2,
            "max_requests_per_round": 3,
            "max_input_tokens": 20000,
            "max_evidence_bytes": 80000,
        },
        "confidence": {
            "metric": "selected_probability",
            "compliant_min": None,
            "violation_min": None,
            "request_selection_min": None,
            "support_min": None,
            "calibration_id": None,
        },
        "feedback": {
            "violation": "Review the cited change.",
            "repair_guidance": "Keep the decision in Service.",
        },
        "ci": {
            "severity": "warning",
            "compliant": "report",
            "violation": "warn",
            "uncertain": "report",
        },
    }
    (policies / "policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
    config = {
        "schema_version": "jev.config/0.2",
        "mode": "calibration",
        "control_bundle": {
            "id": "fixture",
            "root": str(control),
            "revision": "fixture-1",
        },
        "document_bindings": [
            {
                "id": "architecture",
                "path": "architecture.md",
                "sha256": hashlib.sha256(doc).hexdigest(),
                "authority": "trusted",
            }
        ],
        "inference": {
            "adapter": "vercel-typesafe",
            "model": "typesafe-ai/jev",
            "endpoint": ENDPOINT,
            "credential_env": "AI_GATEWAY_API_KEY",
            "timeout_seconds": 5,
            "max_request_bytes": 100000,
            "max_response_bytes": 20000,
            "max_questions": 8,
        },
        "providers": {"enabled": ["git-exact"]},
        "diff": {
            "strategy": "bounded-sequential-v1",
            "max_chunk_bytes": 1200,
            "max_total_diff_bytes": 200000,
            "max_chunks": 20,
        },
        "limits": {
            "max_policies": 4,
            "max_policy_bytes": 65536,
            "max_policy_folder_bytes": 200000,
            "max_calls": 20,
            "max_seconds": 30,
            "max_rounds": 2,
            "max_candidates": 12,
            "max_evidence_bytes": 80000,
            "max_search_results": 20,
            "max_input_bytes": 100000,
        },
        "ci": {"incomplete": "report", "operational_error": "error"},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return {
        "repo": repo,
        "base": base,
        "head": head,
        "control": control,
        "policies": policies,
        "policy": policy,
        "config": config,
        "config_path": config_path,
    }
