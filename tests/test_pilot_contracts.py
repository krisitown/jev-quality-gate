from __future__ import annotations

import json

import httpx
import pytest

from conftest import git
from jev_ci.coordinator import evaluate
from jev_ci.evaluator import meets_threshold
from jev_ci.inference import Gateway
from jev_ci.reporting import render_text
from jev_ci.trace import verify_pack
from test_protocol import response, run


@pytest.mark.parametrize("name", ["disposition", "support", "next_request"])
def test_declared_answers_drive_verdict_and_retrieval(
    project, tmp_path, monkeypatch, name
):
    seen = []
    selections = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(state)
        initial = state["unit_kind"] == "chunk" and state["round"] == 0
        support = next(
            k for k in body["questions"]["support"]["criteria"] if k != "none"
        )
        selected_request = next(
            (
                c["id"]
                for c in state["candidate_menu"]
                if c["request"]["type"] == "GET_FILE"
            ),
            None,
        )
        selections.append(selected_request)
        disposition = (
            "need_more_evidence" if name == "next_request" and initial else "violation"
        )
        result = response(body, disposition, support, selected_request)
        payload = json.loads(result.content)
        selection = payload["answers"][name]["choice"]
        other = next(k for k in body["questions"][name]["criteria"] if k != selection)
        payload["answers"][name]["probabilities"] = {
            k: 0.49 if k == selection else 0.51 if k == other else 0
            for k in body["questions"][name]["criteria"]
        }
        return httpx.Response(200, json=payload)

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "violation"
    assert not summary["errors"]
    if name == "next_request":
        assert selections[0] in seen[1]["delivered_evidence"]
    events = [
        json.loads(line) for line in (pack / "events.jsonl").read_text().splitlines()
    ]
    assert any(
        e["payload"].get("choice_probability_mismatches") == [name]
        for e in events
        if e["type"] == "gateway_attempt"
    )
    assert verify_pack(pack)["status"] == "verified"


@pytest.mark.parametrize("fail_after_round", [0, 1])
@pytest.mark.parametrize("http_status", [400, 503])
def test_native_context_limit_is_uncertain_without_retry_or_run_abort(
    project, tmp_path, monkeypatch, fail_after_round, http_status
):
    attempts = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        attempts.append(state)
        if state["unit_kind"] == "chunk":
            if state["round"] == fail_after_round:
                # Actual native error shape preserved from the prior calibration.
                return httpx.Response(
                    http_status,
                    json={
                        "error": {
                            "message": '{"error_type":"max_tokens_exceeded"}',
                            "type": "AI_APICallError",
                        }
                    },
                )
            return response(body, "need_more_evidence")
        return response(body, "compliant")

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["exit_code"] == 0
    assert summary["status"] == "completed_with_findings"
    assert not summary["errors"]
    assert summary["diagnostics"][0]["reason"] == "context_budget_exceeded"
    assert len(attempts) == fail_after_round + 2  # includes later reconciliation
    assert verify_pack(pack)["status"] == "verified"


def test_finding_packet_is_stable_across_commits_and_reopens_after_source_changes(
    project, tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fixture-key")

    def mock(request):
        body = json.loads(request.content)
        support = next(
            k for k in body["questions"]["support"]["criteria"] if k != "none"
        )
        return response(body, "violation", support)

    def finding(label):
        pack = tmp_path / label
        summary = evaluate(
            project["repo"],
            "feature",
            "main",
            project["config_path"],
            project["policies"],
            pack,
            transport=httpx.MockTransport(mock),
        )
        result = summary["policies"][0]["findings"][0]
        assert result["policy_statement"] == project["policy"]["statement"]
        assert "x + 1" in result["related_diff"][0]["content"]
        assert result["evidence_id"] and result["evidence"]
        assert result["finding_id"] in render_text(summary)
        assert "x + 1" in (pack / "report.md").read_text()
        assert (
            json.loads((pack / "feedback.json").read_text())["schema_version"]
            == "jev.feedback/0.2"
        )
        assert verify_pack(pack)["status"] == "verified"
        return result

    first = finding("first")
    git(project["repo"], "checkout", "feature")
    (project["repo"] / "README.md").write_text("unrelated addition\n")
    git(project["repo"], "add", ".")
    git(project["repo"], "commit", "-m", "unrelated")
    second = finding("second")
    assert second["chunk_id"] != first["chunk_id"]
    assert second["finding_id"] == first["finding_id"]
    service = project["repo"] / "src/Service.java"
    service.write_text(service.read_text().replace("calculate(4)", "calculate(5)"))
    git(project["repo"], "add", ".")
    git(project["repo"], "commit", "-m", "change relevant source")
    third = finding("third")
    assert third["finding_id"] != first["finding_id"]


def test_evaluator_injection_uses_the_shared_controller_without_gateway_credentials(
    project, tmp_path, monkeypatch
):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)

    def mock(request):
        return response(json.loads(request.content), "compliant")

    # A supplied implementation shares menus, size checks, feedback and replay.
    adapter = Gateway(
        project["config"]["inference"],
        "fixture-key",
        transport=httpx.MockTransport(mock),
    )
    pack = tmp_path / "injected"
    summary = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        pack,
        evaluator=adapter,
    )
    assert summary["status"] == "completed"
    assert (
        json.loads((pack / "manifest.json").read_text())["evaluator"]
        == adapter.identity
    )
    assert verify_pack(pack)["status"] == "verified"
    assert meets_threshold({"selected_probability": None}, None)
    assert not meets_threshold({"selected_probability": None}, 0.5)


def test_preflight_error_without_protocol_manifest_still_replays(project, tmp_path):
    config = project["config_path"]
    config.write_text("{}")
    pack = tmp_path / "preflight-error"
    summary = evaluate(
        project["repo"], "feature", "main", config, project["policies"], pack
    )
    assert summary["status"] == "error"
    assert not (pack / "manifest.json").exists()
    assert verify_pack(pack)["status"] == "verified"
