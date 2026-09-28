from __future__ import annotations

import json

import pytest
from ruamel.yaml.error import YAMLError

from jev_ci.config import load_config
from jev_ci.diff_chunking import chunk_diff
from jev_ci.errors import ComparisonError, ConfigError
from jev_ci.git import compare
from jev_ci.policy import load_policies, parse_policy_yaml


def test_branch_comparison_uses_merge_base_and_excludes_dirty_state(project):
    (project["repo"] / "src" / "Service.java").write_text("dirty edit\n")
    change = compare(project["repo"], "feature", "main", 200000)
    assert change.base == project["base"]
    assert change.source == project["head"]
    assert change.dirty
    assert change.paths == ("src/Service.java",)
    assert b"dirty edit" not in change.raw_diff
    assert b"target advanced" not in change.raw_diff


def test_chunking_reconstructs_every_byte_with_tiny_cap(project):
    change = compare(project["repo"], "feature", "main", 200000)
    limits = {
        "strategy": "bounded-sequential-v1",
        "max_chunk_bytes": 290,
        "max_total_diff_bytes": 200000,
        "max_chunks": 50,
    }
    manifest = chunk_diff(change, limits)
    assert manifest.status == "complete"
    assert len(manifest.chunks) > 1
    assert (
        b"".join(chunk.content.encode() for chunk in manifest.chunks) == change.raw_diff
    )
    assert all(
        len(
            json.dumps(chunk.envelope(), sort_keys=True, separators=(",", ":")).encode()
        )
        <= 290
        for chunk in manifest.chunks
    )


def test_policy_folder_rejects_duplicate_keys_aliases_and_duplicate_ids(project):
    config = load_config(project["config_path"])
    root = project["policies"]
    original = (root / "policy.yaml").read_text()
    (root / "policy.yaml").write_text(original + "id: duplicate\n")
    with pytest.raises(ConfigError, match="duplicate"):
        load_policies(root, config)
    (root / "policy.yaml").write_text(original)
    (root / "second.yml").write_text(original)
    with pytest.raises(ConfigError, match="duplicate policy ID"):
        load_policies(root, config)
    (root / "second.yml").unlink()
    (root / "policy.yaml").write_text(original.replace("src/**", "*alias"))
    with pytest.raises(ConfigError):
        load_policies(root, config)
    with pytest.raises(ValueError, match="merge"):
        parse_policy_yaml(b"nested: {<<: {a: 1}}\n")
    with pytest.raises(ValueError, match="custom"):
        parse_policy_yaml(b"id: !custom hello\n")
    with pytest.raises(YAMLError):
        parse_policy_yaml(b"id: first\n---\nid: second\n")


def test_gate_requires_calibration(project):
    config = project["config"]
    config["mode"] = "gate"
    project["config_path"].write_text(json.dumps(config))
    with pytest.raises(ConfigError, match="calibrated thresholds"):
        load_policies(project["policies"], load_config(project["config_path"]))


def test_yaml_12_plain_text_and_duplicate_json_keys(project):
    config = load_config(project["config_path"])
    policy_file = project["policies"] / "policy.yaml"
    policy_file.write_text(
        policy_file.read_text().replace("id: business-decision-placement", "id: on")
    )
    assert load_policies(project["policies"], config).policies[0].id == "on"
    source = project["config_path"].read_text()
    project["config_path"].write_text(
        source.replace('"mode": "calibration"', '"mode": "calibration", "mode": "gate"')
    )
    with pytest.raises(ConfigError, match="duplicate JSON key"):
        load_config(project["config_path"])


def test_diff_limit_is_incomplete_not_prefix_evaluation(project):
    change = compare(project["repo"], "feature", "main", 40)
    assert change.diff_exceeded
    manifest = chunk_diff(change, project["config"]["diff"])
    assert manifest.status == "incomplete"
    assert manifest.reason == "diff_limit_exceeded"
    assert not manifest.chunks


def test_nul_safe_path_inventory_and_deletion_snapshot(project):
    from conftest import git

    repo = project["repo"]
    git(repo, "checkout", "feature")
    (repo / "src" / "odd\tname.java").write_text("class Odd {}\n")
    (repo / "src" / "Service.java").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "odd path and deletion")
    change = compare(repo, "feature", "main", 200000)
    assert "src/odd\tname.java" in change.paths
    assert "src/Service.java" in change.paths
    manifest = chunk_diff(change, project["config"]["diff"])
    assert manifest.status == "complete"
    assert (
        b"".join(chunk.content.encode() for chunk in manifest.chunks) == change.raw_diff
    )
    from jev_ci.git import show_file

    assert b"class Service" in show_file(change, "base", "src/Service.java", 10000)
    with pytest.raises(ComparisonError):
        show_file(change, "head", "src/Service.java", 10000)
