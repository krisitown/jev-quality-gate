"""Opt-in executable fixture gate: JEV_CI_RIPWIRE_BIN must name Ripwire 0.6.5."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from jev_ci.coordinator import evaluate
from jev_ci.git import compare
from jev_ci.providers import RipwireProvider
from conftest import git
from test_evaluation import answer


def test_ripwire_committed_snapshot_callers_callees_and_limits(project):
    binary_name = os.environ.get("JEV_CI_RIPWIRE_BIN")
    if not binary_name:
        pytest.skip("set JEV_CI_RIPWIRE_BIN to run the pinned executable fixture")
    binary = Path(binary_name).resolve()
    assert binary.is_file()
    settings = {
        "binary": str(binary),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "version": "0.6.5",
        "timeout_seconds": 10,
        "max_output_bytes": 50000,
        "max_snapshot_bytes": 1000000,
        "max_symbols": 100,
    }
    change = compare(project["repo"], "feature", "main", 200000)
    with RipwireProvider(change, settings) as provider:
        symbols, coverage = provider.changed_symbols(change.paths)
        assert any(item["name"] == "calculate" for item in symbols)
        callers = provider.relation("GET_CALLERS", "calculate")
        callees = provider.relation("GET_CALLEES", "handle")
    assert any(item["name"] == "handle" for item in callers["items"])
    assert any(item["name"] == "calculate" for item in callees["items"])
    assert callers["coverage"] == "partial"
    assert callers["counts_floor"] is True
    assert callers["snapshot"] == project["head"]


def test_ripwire_disambiguates_same_named_methods(project):
    binary_name = os.environ.get("JEV_CI_RIPWIRE_BIN")
    if not binary_name:
        pytest.skip("set JEV_CI_RIPWIRE_BIN to run the pinned executable fixture")
    repo = project["repo"]
    git(repo, "checkout", "feature")
    (repo / "src" / "Other.java").write_text(
        "class Other { int calculate(int x) { return x - 1; } }\n"
    )
    (repo / ".gitattributes").write_text("src/Service.java export-ignore\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "duplicate method name")
    binary = Path(binary_name).resolve()
    settings = {
        "binary": str(binary),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "version": "0.6.5",
        "timeout_seconds": 10,
        "max_output_bytes": 50000,
        "max_snapshot_bytes": 1000000,
        "max_symbols": 100,
    }
    change = compare(repo, "feature", "main", 200000)
    with RipwireProvider(change, settings) as provider:
        ambiguous = provider.relation("GET_CALLERS", "calculate")
        precise = provider.relation("GET_CALLERS", "src/Service.java:calculate")
    assert ambiguous["definitions"] == 2
    assert precise["definitions"] == 1
    assert any(row["name"] == "handle" for row in precise["items"])


def test_ripwire_evidence_is_offered_and_delivered(project, tmp_path, monkeypatch):
    binary_name = os.environ.get("JEV_CI_RIPWIRE_BIN")
    if not binary_name:
        pytest.skip("set JEV_CI_RIPWIRE_BIN to run the pinned executable fixture")
    binary = Path(binary_name).resolve()
    config = project["config"]
    config["providers"] = {
        "enabled": ["git-exact", "ripwire"],
        "ripwire": {
            "binary": str(binary),
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "version": "0.6.5",
            "timeout_seconds": 10,
            "max_output_bytes": 50000,
            "max_snapshot_bytes": 1000000,
            "max_symbols": 100,
        },
    }
    project["config_path"].write_text(json.dumps(config))
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret")
    seen_relation = []

    def mock(request):
        body = json.loads(request.content)
        state, questions = body["state"], body["questions"]
        selected = {
            "disposition": "violation",
            "support": next(iter(state["delivered_evidence"])),
        }
        if state["unit_kind"] == "chunk" and state["round"] == 0:
            selected["disposition"] = "need_more_evidence"
            selected["support"] = "none"
            selected["next_request"] = next(
                c["id"]
                for c in state["candidate_menu"]
                if c["request"]["type"] == "GET_CALLERS"
                and c["request"]["target"]["symbol"] == "calculate"
            )
        if state["unit_kind"] == "chunk" and state["round"] == 1:
            seen_relation.extend(
                x
                for x in state["delivered_evidence"].values()
                if isinstance(x, dict) and x.get("type") == "GET_CALLERS"
            )
            selected["support"] = next(
                k
                for k, x in state["delivered_evidence"].items()
                if x.get("type") == "GET_CALLERS"
            )
        answers = {
            name: answer(question, selected.get(name, next(iter(question["criteria"]))))
            for name, question in questions.items()
        }
        return httpx.Response(200, json={"answers": answers})

    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        tmp_path / "pack",
        transport=httpx.MockTransport(mock),
    )
    assert result["status"] == "completed_with_findings", result["errors"]
    assert seen_relation
    assert seen_relation[0]["items"][0]["content"]["definitions"] == 1
    assert seen_relation[0]["items"][0]["content"]["coverage"] == "partial"
