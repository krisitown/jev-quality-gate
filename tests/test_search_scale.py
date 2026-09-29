from __future__ import annotations

import json
import time

import pytest

from jev_ci.config import load_config
from jev_ci.context import Candidate, retrieve
from jev_ci.diff_chunking import chunk_diff
from jev_ci.git import compare, iter_tree_blobs
from jev_ci.policy import load_policies
from conftest import git


def test_tree_blob_reader_batches_many_files_and_keeps_export_ignored_files(
    project, monkeypatch
):
    repo = project["repo"]
    git(repo, "checkout", "feature")
    for index in range(80):
        (repo / "src" / f"File{index:03}.java").write_text(f"class F{index} {{}}\n")
    (repo / ".gitattributes").write_text("src/File000.java export-ignore\n")
    (repo / "src" / "link.java").symlink_to("File001.java")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "many committed files")
    commit = git(repo, "rev-parse", "HEAD")

    import jev_ci.process as process_module

    actual_popen = process_module.subprocess.Popen
    launches = []

    def counted_popen(*args, **kwargs):
        launches.append(args[0])
        return actual_popen(*args, **kwargs)

    monkeypatch.setattr(process_module.subprocess, "Popen", counted_popen)
    stats = {}
    blobs = dict(
        (path, content)
        for path, _oid, content in iter_tree_blobs(
            repo,
            commit,
            max_file_bytes=1000,
            max_total_bytes=100000,
            stats=stats,
        )
    )

    assert len(blobs) >= 80
    assert "src/File000.java" in blobs
    assert "src/link.java" not in blobs
    assert "src/link.java" in stats["skipped_paths"]
    assert len(launches) == 3


def test_tree_blob_reader_stops_when_deadline_is_expired(project):
    with pytest.raises(TimeoutError, match="deadline"):
        list(
            iter_tree_blobs(
                project["repo"],
                project["head"],
                max_file_bytes=100,
                max_total_bytes=1000,
                deadline=time.monotonic() - 1,
            )
        )


def test_search_code_returns_exact_matches_and_marks_skipped_content_partial(project):
    repo = project["repo"]
    git(repo, "checkout", "main")
    (repo / "src" / "C.java").write_bytes(b"needle\x00binary\n")
    (repo / "src" / "E.java").write_bytes(b"\xff\xfe")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "committed binary search fixtures")
    git(repo, "checkout", "feature")
    git(repo, "rebase", "main")
    (repo / "src" / "A.java").write_text("class A { // needle exact\n}\n")
    (repo / "src" / "B.java").write_text("x" * 2100 + " needle\n")
    (repo / "src" / "D.java").write_text("x" * 700 + "needle" + "y" * 700 + "\n")
    (repo / "src" / "Link.java").symlink_to("A.java")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "search fixtures")

    config_data = project["config"]
    config_data["limits"]["max_evidence_bytes"] = 2000
    project["config_path"].write_text(json.dumps(config_data))
    policy_file = project["policies"] / "policy.yaml"
    policy_file.write_text(
        policy_file.read_text().replace(
            "max_evidence_bytes: 80000", "max_evidence_bytes: 2000"
        )
    )
    config = load_config(project["config_path"])
    policy = load_policies(project["policies"], config).policies[0]
    change = compare(repo, "feature", "main", 200000)
    chunks = chunk_diff(change, config.diff)
    candidate = Candidate(
        "search-candidate",
        {"type": "SEARCH_CODE", "target": {"literal": "needle", "snapshot": "head"}},
        "fixture exact search",
    )

    evidence = retrieve(candidate, policy, change, chunks, config, None)

    assert evidence["status"] == "partial"
    assert evidence["coverage"] == "partial"
    assert [item["path"] for item in evidence["items"]] == [
        "src/A.java",
        "src/D.java",
    ]
    long_match = evidence["items"][1]
    assert "needle" in long_match["content"]
    assert len(long_match["content"]) <= 500
    assert long_match["line_truncated"] is True
    assert long_match["column_range"][0] > 1
    assert len(long_match["line_sha256"]) == 64
    assert evidence["skipped_files"] >= 4
    assert "src/B.java" in evidence["skipped_paths"]
    assert "src/C.java" in evidence["skipped_paths"]
    assert "src/Link.java" in evidence["skipped_paths"]
    assert "src/E.java" in evidence["skipped_paths"]

    file_candidate = Candidate(
        "binary-file-candidate",
        {"type": "GET_FILE", "target": {"path": "src/C.java", "snapshot": "head"}},
        "fixture binary file",
    )
    binary_evidence = retrieve(file_candidate, policy, change, chunks, config, None)
    assert binary_evidence["status"] == "partial"
    assert not binary_evidence["items"]
