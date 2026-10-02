from __future__ import annotations

import json

import httpx
import pytest

from jev_ci.coordinator import evaluate
from jev_ci.trace import verify_pack
from test_evaluation import answer


def run(project, tmp_path, monkeypatch, mock):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fixture-key")
    pack = tmp_path / "pack"
    summary = evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        pack,
        transport=httpx.MockTransport(mock),
    )
    return summary, pack


@pytest.mark.parametrize(
    "proposed",
    ["compliant", "violation", "uncertain", "need_more_evidence", "policy_ambiguous"],
)
def test_terminal_verdict_precedes_request_otherwise_top_one_is_retrieved(
    project, tmp_path, monkeypatch, proposed
):
    seen = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(state)
        initial = state["unit_kind"] == "chunk" and state["round"] == 0
        selection = {
            "disposition": proposed
            if initial or proposed == "violation"
            else "compliant",
            "support": next(
                k for k in body["questions"]["support"]["criteria"] if k != "none"
            )
            if proposed == "violation"
            else "none",
            "next_request": next(
                c["id"]
                for c in state["candidate_menu"]
                if c["request"]["type"] == "GET_FILE"
            )
            if initial
            else next(iter(body["questions"]["next_request"]["criteria"])),
        }
        assert "none_useful" not in body["questions"]["next_request"]["criteria"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    name: answer(q, selection[name])
                    for name, q in body["questions"].items()
                }
            },
        )

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    terminal = proposed in {"compliant", "violation"}
    assert summary["policies"][0]["outcome"] == (
        "violation" if proposed == "violation" else "compliant"
    )
    assert len(seen) == (2 if terminal else 3)
    if not terminal:
        assert any(
            e["type"] == "GET_FILE" for e in seen[1]["delivered_evidence"].values()
        )
    assert verify_pack(pack)["validated_responses"] == len(seen)


def test_single_chunk_reconciliation_receives_source_and_decimal_costs(
    project, tmp_path, monkeypatch
):
    seen = []

    def mock(request):
        body = json.loads(request.content)
        seen.append(body["state"])
        return httpx.Response(
            200,
            json={
                "answers": {
                    name: answer(
                        q,
                        "compliant"
                        if name == "disposition"
                        else "none"
                        if name == "support"
                        else next(iter(q["criteria"])),
                    )
                    for name, q in body["questions"].items()
                },
                "provider_metadata": {
                    "gateway": {"cost": "0.1" if len(seen) == 1 else "0.2"}
                },
            },
        )

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert seen[-1]["unit_kind"] == "reconciliation"
    assert any(
        e["type"] == "GET_DIFF_CHUNK" for e in seen[-1]["delivered_evidence"].values()
    )
    assert "rounds" not in seen[-1]["prior_units"][0]
    assert summary["coverage"]["native_usage"]["cost_usd"] == "0.3"
    assert summary["coverage"]["native_usage"]["cost_reports"] == 2
    assert verify_pack(pack)["status"] == "verified"


def test_malformed_choice_seals_a_replayable_error_pack(project, tmp_path, monkeypatch):
    def mock(request):
        body = json.loads(request.content)
        responses = {
            name: answer(q, next(iter(q["criteria"])))
            for name, q in body["questions"].items()
        }
        responses["disposition"]["choice"] = []
        return httpx.Response(200, json={"answers": responses})

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["status"] == "error"
    assert summary["exit_code"] == 2
    assert summary["coverage"]["calls_used"] == 1
    assert verify_pack(pack)["validated_responses"] == 0


def response(body, disposition, support="none", request_id=None):
    selections = {"disposition": disposition, "support": support}
    if "next_request" in body["questions"]:
        selections["next_request"] = request_id or next(
            iter(body["questions"]["next_request"]["criteria"])
        )
    return httpx.Response(
        200,
        json={
            "answers": {
                name: answer(q, selections[name])
                for name, q in body["questions"].items()
            }
        },
    )


def configure(project, **limits):
    project["config"]["limits"].update(limits)
    project["config_path"].write_text(json.dumps(project["config"]))


def test_root_count_limit_overrides_legacy_policy_count(project, tmp_path, monkeypatch):
    configure(project, max_rounds=1000000)
    seen = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(state)
        return response(
            body,
            "compliant"
            if state["unit_kind"] == "reconciliation" or state["round"] == 3
            else "uncertain",
        )

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "compliant"
    assert [s["round"] for s in seen if s["unit_kind"] == "chunk"] == [0, 1, 2, 3]
    assert project["policy"]["evidence"]["max_rounds"] == 2
    assert verify_pack(pack)["validated_responses"] == 5


def test_configurable_count_limit_stops_unresolved_loop(project, tmp_path, monkeypatch):
    configure(project, max_rounds=1)

    def mock(request):
        return response(json.loads(request.content), "uncertain")

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "uncertain"
    assert {d["reason"] for d in summary["diagnostics"]} == {"round_limit"}
    assert verify_pack(pack)["validated_responses"] == 4


def test_empty_retrieval_is_disclosed_then_another_candidate_is_fetched(
    project, tmp_path, monkeypatch
):
    import jev_ci.protocol as protocol

    original = protocol.retrieve
    fetched = []
    configure(project, max_rounds=1000000)

    def retrieve(candidate, *args, **kwargs):
        fetched.append(candidate.id)
        if len(fetched) == 1:
            return {
                "type": "GET_FILE",
                "candidate_id": candidate.id,
                "status": "empty",
                "items": [],
                "coverage": "partial",
            }
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(protocol, "retrieve", retrieve)
    seen = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(body)
        return response(
            body,
            "compliant"
            if state["unit_kind"] == "reconciliation" or state["round"] == 2
            else "need_more_evidence",
        )

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "compliant"
    assert len(fetched) == len(set(fetched)) == 2
    assert seen[1]["state"]["delivered_evidence"][fetched[0]]["status"] == "empty"
    assert fetched[0] not in seen[1]["questions"]["support"]["criteria"]
    assert verify_pack(pack)["validated_responses"] == 4


def test_fetched_content_crossing_input_cap_is_not_sent(project, tmp_path, monkeypatch):
    import jev_ci.protocol as protocol

    configure(project, max_rounds=1000000, max_input_bytes=10000)

    def retrieve(candidate, *args, **kwargs):
        return {
            "type": "GET_FILE",
            "candidate_id": candidate.id,
            "status": "ok",
            "coverage": "complete_for_declared_scope",
            "items": [{"path": "src/Service.java", "content": "x" * 11000}],
        }

    monkeypatch.setattr(protocol, "retrieve", retrieve)
    sent = []

    def mock(request):
        assert len(request.content) <= 10000
        body = json.loads(request.content)
        sent.append(body)
        return response(
            body,
            "compliant"
            if body["state"]["unit_kind"] == "reconciliation"
            else "uncertain",
        )

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert len(sent) == 2
    assert summary["diagnostics"][0]["reason"] == "input_byte_limit"
    events = [
        json.loads(line) for line in (pack / "events.jsonl").read_text().splitlines()
    ]
    assert any(
        e["type"] == "input_limit_reached" and e["payload"]["request_bytes"] > 10000
        for e in events
    )
    assert any(
        e["type"] == "evidence_returned"
        and len(e["payload"]["items"][0]["content"]) == 11000
        for e in events
    )
    assert verify_pack(pack)["validated_responses"] == 2


def test_menu_omissions_do_not_veto_compliance(project, tmp_path, monkeypatch):
    configure(project, max_candidates=1)

    def mock(request):
        body = json.loads(request.content)
        assert body["state"]["candidate_omissions"] > 0
        return response(body, "compliant")

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "compliant"
    assert verify_pack(pack)["validated_responses"] == 2


def test_exhausted_candidates_preserve_uncertainty(project, tmp_path, monkeypatch):
    configure(project, max_rounds=1000000)

    def mock(request):
        return response(json.loads(request.content), "uncertain")

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "uncertain"
    assert {d["reason"] for d in summary["diagnostics"]} == {"candidate_exhausted"}
    assert verify_pack(pack)["status"] == "verified"


def test_retrieved_diff_chunk_is_valid_source_support():
    from jev_ci.protocol import _anchors, questions

    chunk = {"id": "chunk-1", "paths": ["src/Service.java"], "start": 0, "end": 50}
    evidence = {"type": "GET_DIFF_CHUNK", "status": "ok", "items": [{"content": chunk}]}
    anchors, precision = _anchors(evidence)
    assert anchors == [
        {"path": "src/Service.java", "chunk_id": "chunk-1", "raw_range": [0, 50]}
    ]
    assert precision == "file"
    assert (
        "retrieved-chunk"
        in questions([], {"retrieved-chunk": evidence})["support"]["criteria"]
    )


def test_request_probability_never_suppresses_top_one_acquisition(
    project, tmp_path, monkeypatch
):
    import yaml

    policy = project["policy"]
    policy["confidence"]["request_selection_min"] = 0.99
    (project["policies"] / "policy.yaml").write_text(yaml.safe_dump(policy))
    seen = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(state)
        initial = state["unit_kind"] == "chunk" and state["round"] == 0
        result = response(body, "uncertain" if initial else "compliant")
        data = json.loads(result.content)
        if initial:
            keys = list(body["questions"]["next_request"]["criteria"])
            assert len(keys) == 3
            data["answers"]["next_request"]["probabilities"] = dict(
                zip(keys, [0.4, 0.3, 0.3])
            )
        return httpx.Response(200, json=data)

    summary, pack = run(project, tmp_path, monkeypatch, mock)
    assert summary["policies"][0]["outcome"] == "compliant"
    assert len(seen) == 3
    assert verify_pack(pack)["validated_responses"] == 3


def test_legacy_policy_token_field_is_not_a_byte_ceiling(
    project, tmp_path, monkeypatch
):
    import yaml

    policy = project["policy"]
    policy["evidence"]["max_input_tokens"] = 1
    (project["policies"] / "policy.yaml").write_text(yaml.safe_dump(policy))
    summary, pack = run(
        project,
        tmp_path,
        monkeypatch,
        lambda request: response(json.loads(request.content), "compliant"),
    )
    assert summary["policies"][0]["outcome"] == "compliant"
    assert verify_pack(pack)["validated_responses"] == 2
