from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from jev_ci.process import ProcessResult

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.public_prs import run as harness


class FakeRunner:
    def __init__(self, *, merge_base: str | None = None):
        self.calls: list[tuple[list[str], dict]] = []
        self.merge_base = merge_base

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if "merge-base" in args:
            output = self.merge_base
        elif "refs/jev/head^{commit}" in args:
            output = harness.load_cases()["flask-6145"]["head_commit"]
        elif any(value.endswith("^{commit}") for value in args):
            output = next(value[:-9] for value in args if value.endswith("^{commit}"))
        elif "rev-parse" in args and "HEAD" in args:
            output = harness.load_cases()["flask-6145"]["head_commit"]
        else:
            output = ""
        return ProcessResult(0, output.encode("ascii"), b"", False)


def test_frozen_controls_are_verified_and_report_only(tmp_path):
    cases = harness.load_cases()
    assert set(cases) == {"flask-6145", "gin-4806", "svelte-18535"}
    for case in cases.values():
        provenance = harness.verify_controls(case)
        assert provenance["mode"] == "calibration"
        assert provenance["actions"] == "report-only"
        assert set(provenance["policies"])

    copied = tmp_path / "controls"
    shutil.copytree(harness.HARNESS_ROOT / "controls", copied)
    convention = copied / "flask-6145" / "convention.md"
    convention.write_text(convention.read_text() + "edited\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        harness.verify_controls(cases["flask-6145"], copied)


def test_prepare_uses_only_fixed_git_operations_and_checks_unique_merge_base(
    tmp_path, monkeypatch
):
    case = harness.load_cases()["flask-6145"]
    fake = FakeRunner(merge_base=case["expected_merge_base"])
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-secret-must-not-reach-git")
    output = tmp_path / "prepared"
    output.mkdir()
    record = harness.prepare_case(case, output, runner=fake)

    assert record["head_commit"] == case["head_commit"]
    assert record["merge_base"] == case["expected_merge_base"]
    assert record["candidate_code_executed"] is False
    assert (output / "prepared" / "flask-6145.json").is_file()
    assert any(
        f"+{case['head_commit']}:refs/jev/head" in args for args, _ in fake.calls
    )
    assert any("--filter=blob:none" in args for args, _ in fake.calls)
    assert not any("refs/pull/" in " ".join(args) for args, _ in fake.calls)
    assert all(args[0] == "git" for args, _kwargs in fake.calls)
    assert all(
        "AI_GATEWAY_API_KEY" not in (kwargs.get("env") or {})
        for _args, kwargs in fake.calls
    )
    assert any("--detach" in args for args, _ in fake.calls)
    assert not any(
        "./configure" in args or "make" in args or "pytest" in args
        for args, _ in fake.calls
    )

    mismatch = FakeRunner(merge_base="0" * 40)
    with pytest.raises(ValueError, match="expected unique merge base"):
        harness.prepare_case(case, tmp_path / "mismatch", runner=mismatch)


def test_case_metadata_keeps_public_pr_identity_and_scale():
    cases = harness.load_cases()
    flask = cases["flask-6145"]
    gin = cases["gin-4806"]
    svelte = cases["svelte-18535"]
    assert flask["pull_request_url"].endswith("/pull/6145")
    assert flask["repository_url"] == "https://github.com/pallets/flask"
    assert gin["language"] == "Go"
    assert gin["license_family"] == "MIT"
    assert svelte["size"]["changed_lines"] > gin["size"]["changed_lines"]
    assert svelte["size"]["scoped_source_test_changed_lines"] == 705
    assert svelte["size"]["broader_source_test_changed_lines"] == 741


@pytest.mark.parametrize(
    (
        "evaluation_status",
        "evaluation_code",
        "replay_status",
        "replay_code",
        "expected",
    ),
    [
        ("completed_with_findings", 0, "verified", 0, 0),
        ("error", 2, "verified", 0, 2),
        ("completed_with_findings", 0, "error", 2, 2),
    ],
)
def test_harness_exit_preserves_report_only_uncertainty_but_rejects_errors(
    tmp_path,
    monkeypatch,
    evaluation_status,
    evaluation_code,
    replay_status,
    replay_code,
    expected,
):
    import json

    output = tmp_path / "harness-run"
    monkeypatch.setattr(harness, "_tool_command", lambda _: ["fake-jev-ci"])
    monkeypatch.setattr(
        harness, "prepare_case", lambda case, root: {"case": case["id"]}
    )
    monkeypatch.setattr(
        harness,
        "evaluate_case",
        lambda *args: {
            "evaluation_status": evaluation_status,
            "evaluation_exit_code": evaluation_code,
            "replay_status": replay_status,
            "replay_exit_code": replay_code,
            "inspect_status": evaluation_status,
            "inspect_exit_code": 0,
        },
    )
    assert (
        harness.main(["--output", str(output), "--case", "flask-6145", "--evaluate"])
        == expected
    )
    saved = json.loads((output / "run-summary.json").read_text())
    assert saved["evaluated"][0]["evaluation_status"] == evaluation_status
    assert saved["evaluated"][0]["replay_status"] == replay_status
