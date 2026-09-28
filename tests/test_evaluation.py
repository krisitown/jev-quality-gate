from __future__ import annotations

import json

import httpx
import pytest

from jev_ci.coordinator import evaluate
from jev_ci.inference import Gateway, validate_answers
from jev_ci.trace import verify_pack
from jev_ci.errors import InferenceError, TraceError


def answer(question: dict, selection: str) -> dict:
    return {
        "type": "choice",
        "choice": selection,
        "probabilities": {key: float(key == selection) for key in question["criteria"]},
        "confidence": 0.9,
    }


def test_branch_evaluation_adapts_reconciles_and_replays(
    project, tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret-value")
    requests = []

    def mock(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer mock-secret-value"
        body = json.loads(request.content)
        requests.append(body)
        state, questions = body["state"], body["questions"]
        if state["unit_kind"] == "reconciliation":
            disposition = "violation"
        elif state["round"] == 0:
            disposition = "need_more_evidence"
        else:
            disposition = "violation"
        selected = {"disposition": disposition, "support": "none"}
        if disposition == "need_more_evidence":
            selected["next_request"] = next(
                x["id"]
                for x in state["candidate_menu"]
                if x["request"]["type"] == "GET_FILE"
            )
        if disposition == "violation":
            selected["support"] = next(
                x for x in state["delivered_evidence"] if x != state["chunk_id"]
            )
        answers = {
            name: answer(question, selected.get(name, "none_useful"))
            for name, question in questions.items()
        }
        return httpx.Response(
            200,
            json={
                "model": "typesafe-ai/jev",
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    output = tmp_path / "pack"
    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(mock),
    )
    assert result["status"] == "completed_with_findings", result["errors"]
    assert result["exit_code"] == 0
    assert result["policies"][0]["outcome"] == "violation"
    assert (
        result["policies"][0]["findings"][0]["explanation_origin"] == "policy_template"
    )
    assert result["policies"][0]["findings"][0]["localization"] == "file"
    assert (
        result["policies"][0]["findings"][0]["source_anchors"][0]["path"]
        == "src/Service.java"
    )
    assert len(requests) == 3
    assert result["coverage"]["native_usage"]["input_tokens"] == 300
    assert result["coverage"]["native_usage"]["output_tokens"] == 30
    assert requests[0]["state"]["unit_kind"] == "chunk"
    assert requests[-1]["state"]["unit_kind"] == "reconciliation"
    assert verify_pack(output)["validated_responses"] == 3
    assert "mock-secret-value" not in (output / "events.jsonl").read_text()
    assert "mock-secret-value" not in (output / "manifest.json").read_text()


def test_replay_rejects_tampered_response(project, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret-value")

    def mock(request):
        body = json.loads(request.content)
        answers = {
            name: answer(
                question,
                "compliant"
                if name == "disposition"
                else "none"
                if name == "support"
                else "none_useful",
            )
            for name, question in body["questions"].items()
        }
        return httpx.Response(200, json={"answers": answers})

    output = tmp_path / "pack"
    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(mock),
    )
    assert result["exit_code"] == 0
    assert verify_pack(output)["status"] == "verified"
    blob = next((output / "blobs" / "sha256").iterdir())
    blob.write_bytes(b"tamper")
    with pytest.raises(TraceError, match="checksum mismatch"):
        verify_pack(output)


def test_typed_choice_rejects_fabricated_or_malformed_answers():
    question = {"disposition": {"criteria": {"compliant": "yes", "violation": "no"}}}
    with pytest.raises(InferenceError):
        validate_answers(
            {
                "answers": {
                    "disposition": {
                        "type": "choice",
                        "choice": "compliant",
                        "probabilities": {"compliant": 0.1, "violation": 0.9},
                    }
                }
            },
            question,
        )
    with pytest.raises(InferenceError):
        validate_answers(
            {
                "answers": {
                    "disposition": {
                        "type": "choice",
                        "choice": "compliant",
                        "probabilities": {"compliant": True, "violation": 0.0},
                    }
                }
            },
            question,
        )


def test_gateway_retries_only_one_503():
    settings = {
        "model": "typesafe-ai/jev",
        "endpoint": "https://ai-gateway.vercel.sh/typesafe/v1/systemone",
        "timeout_seconds": 3,
        "max_request_bytes": 10000,
        "max_response_bytes": 10000,
        "max_questions": 8,
    }
    questions = {
        "disposition": {
            "type": "choice",
            "criteria": {"compliant": "yes", "violation": "no"},
        }
    }
    calls = 0

    def mock(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "disposition": answer(questions["disposition"], "compliant")
                }
            },
        )

    import time

    events = []
    result, _ = Gateway(settings, "fake", transport=httpx.MockTransport(mock)).evaluate(
        {}, questions, time.monotonic() + 3, events.append
    )
    assert result["disposition"]["choice"] == "compliant"
    assert calls == 2
    assert [event["status"] for event in events] == [
        "started",
        "received",
        "retry_503",
        "started",
        "received",
        "validated",
    ]


def test_insufficient_call_budget_marks_all_units_unvisited(project, tmp_path):
    config = project["config"]
    config["limits"]["max_calls"] = 1
    project["config_path"].write_text(json.dumps(config))
    output = tmp_path / "pack"
    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
    )
    assert result["status"] == "completed_with_findings"
    assert result["policies"][0]["outcome"] == "uncertain"
    assert result["policies"][0]["unvisited_chunks"]
    assert verify_pack(output)["validated_responses"] == 0


def test_diff_cap_does_not_mislabel_source_as_unsupported(project, tmp_path):
    config = project["config"]
    config["diff"].update(max_chunk_bytes=40, max_total_diff_bytes=40)
    project["config_path"].write_text(json.dumps(config))
    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        tmp_path / "pack",
    )
    assert result["coverage"]["chunk_reason"] == "diff_limit_exceeded"
    assert result["policies"][0]["outcome"] == "uncertain"
    assert result["policies"][0]["unsupported_content"] is False
    assert result["policies"][0]["incomplete_coverage"] is True


def test_diff_cap_with_two_paths_keeps_complete_inventory(project, tmp_path):
    from conftest import git

    repo = project["repo"]
    git(repo, "checkout", "feature")
    (repo / "src" / "Extra.java").write_text("class Extra {}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "second source path")
    config = project["config"]
    config["diff"].update(max_chunk_bytes=40, max_total_diff_bytes=40)
    project["config_path"].write_text(json.dumps(config))
    result = evaluate(
        repo,
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        tmp_path / "pack",
    )
    assert result["coverage"]["chunk_reason"] == "diff_limit_exceeded"
    assert result["comparison"]["paths"] == ["src/Extra.java", "src/Service.java"]
    assert result["policies"][0]["unsupported_content"] is False


def test_binary_change_cannot_be_reported_compliant(project, tmp_path, monkeypatch):
    from conftest import git

    repo = project["repo"]
    git(repo, "checkout", "feature")
    (repo / "src" / "blob.bin").write_bytes(b"\x00\x01\x02")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "binary content")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret")

    def mock(request):
        body = json.loads(request.content)
        answers = {
            name: answer(
                question,
                "compliant"
                if name == "disposition"
                else "none"
                if name == "support"
                else "none_useful",
            )
            for name, question in body["questions"].items()
        }
        return httpx.Response(200, json={"answers": answers})

    result = evaluate(
        repo,
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        tmp_path / "pack",
        transport=httpx.MockTransport(mock),
    )
    assert result["policies"][0]["unsupported_content"] is True
    assert result["policies"][0]["outcome"] == "uncertain"


def test_reconciliation_conflict_is_visible_not_accepted(
    project, tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret")

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        selected = {
            "disposition": "compliant"
            if state["unit_kind"] == "reconciliation"
            else "violation",
            "support": next(iter(state["delivered_evidence"])),
        }
        answers = {
            name: answer(question, selected.get(name, "none_useful"))
            for name, question in body["questions"].items()
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
    assert result["policies"][0]["outcome"] == "uncertain"
    assert result["policies"][0]["conflicts"] == [
        "reconciliation_disagrees_with_supported_chunk_violation"
    ]


def test_gateway_auth_failure_is_operational_error_with_pack(
    project, tmp_path, monkeypatch
):
    from conftest import git

    git(project["repo"], "checkout", "feature")
    source = project["repo"] / "src" / "Service.java"
    source.write_text(
        source.read_text()
        + "".join(
            f"// changed line {i:03d} with enough detail to span chunks\n"
            for i in range(40)
        )
    )
    git(project["repo"], "add", ".")
    git(project["repo"], "commit", "-m", "expand change")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret")
    output = tmp_path / "pack"
    attempts = []

    def reject(request):
        attempts.append(request)
        return httpx.Response(401, json={"echo": "mock-secret"})

    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(reject),
    )
    assert result["exit_code"] == 2
    assert result["status"] == "error"
    assert len(attempts) == 1
    assert result["coverage"]["chunks"] > 1
    assert (
        len(result["policies"][0]["unvisited_chunks"])
        == result["coverage"]["chunks"] - 1
    )
    assert verify_pack(output)["status"] == "verified"
    assert all(
        b"mock-secret" not in file.read_bytes()
        for file in output.rglob("*")
        if file.is_file()
    )


def test_gate_mode_blocks_calibrated_violation(project, tmp_path, monkeypatch):
    import yaml

    config = project["config"]
    config["mode"] = "gate"
    project["config_path"].write_text(json.dumps(config))
    policy = project["policy"]
    policy["ci"]["violation"] = "block"
    policy["confidence"].update(
        compliant_min=0.5,
        violation_min=0.5,
        request_selection_min=0.5,
        support_min=0.5,
        calibration_id="fixture-calibration",
    )
    (project["policies"] / "policy.yaml").write_text(yaml.safe_dump(policy))
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "mock-secret")

    def mock(request):
        body = json.loads(request.content)
        evidence_id = next(iter(body["state"]["delivered_evidence"]))
        answers = {
            name: answer(
                question,
                "violation"
                if name == "disposition"
                else evidence_id
                if name == "support"
                else "none_useful",
            )
            for name, question in body["questions"].items()
        }
        return httpx.Response(200, json={"answers": answers})

    output = tmp_path / "pack"
    result = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(mock),
    )
    assert result["status"] == "blocked"
    assert result["exit_code"] == 1
    assert verify_pack(output)["replayed_aggregates"] == 1
