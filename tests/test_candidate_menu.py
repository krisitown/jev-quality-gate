"""Bounded menus retain useful request categories on large changes."""

from __future__ import annotations

import json

from jev_ci.config import load_config
from jev_ci.context import candidates
from jev_ci.diff_chunking import chunk_diff
from jev_ci.git import compare
from jev_ci.policy import load_policies
from conftest import git


def test_large_file_inventory_does_not_starve_authored_searches(project):
    repo = project["repo"]
    git(repo, "checkout", "feature")
    for index in range(30):
        (repo / "src" / f"Extra{index:02}.java").write_text(
            f"class Extra{index} {{}}\n"
        )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "large file inventory")
    project["config"]["limits"]["max_candidates"] = 5
    project["config_path"].write_text(json.dumps(project["config"]))
    config = load_config(project["config_path"])
    policy = load_policies(project["policies"], config).policies[0]
    change = compare(repo, "feature", "main", 200000)
    chunks = chunk_diff(change, config.diff)
    current = chunks.chunks[-1]
    menu, metadata = candidates(policy, change, chunks, current, set(), config, None)
    assert len(menu) == 5
    assert menu[0].request["type"] == "GET_FILE"
    assert menu[0].request["target"]["path"] in current.paths
    assert {c.request["type"] for c in menu} == {
        "GET_FILE",
        "SEARCH_CODE",
        "GET_DIFF_CHUNK",
        "GET_DOCUMENT",
    }
    assert metadata["omitted"] > 0
    repeat, repeat_metadata = candidates(
        policy, change, chunks, current, set(), config, None
    )
    assert repeat == menu
    assert repeat_metadata == metadata
    used = {c.id for c in menu}
    next_menu, _ = candidates(policy, change, chunks, current, used, config, None)
    assert not used.intersection(c.id for c in next_menu)


def test_aggregate_distinguishes_full_scope_with_uncertain_reconciliation(project):
    from jev_ci.aggregation import aggregate

    config = load_config(project["config_path"])
    policy = load_policies(project["policies"], config).policies[0]
    unit = dict(
        id="chunk-unit", unit_kind="chunk", chunk_id="chunk-1", outcome="compliant"
    )
    reconciliation = dict(
        id="recon",
        unit_kind="reconciliation",
        chunk_id=None,
        outcome="uncertain",
        reason="candidate_gap",
    )
    current = aggregate(policy, [unit], reconciliation, ["chunk-1"], False)
    assert current["outcome"] == "uncertain"
    assert current["reason"] == "unit_uncertainty"
    assert current["unvisited_chunks"] == []
    assert current["incomplete_coverage"] is False
    legacy = aggregate(
        policy, [unit], reconciliation, ["chunk-1"], False, reason_version=1
    )
    assert legacy["reason"] == "incomplete_coverage"
    assert "reason_version" not in legacy
