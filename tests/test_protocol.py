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


@pytest.mark.parametrize("proposed", ["violation", "uncertain"])
def test_selected_missing_fact_is_retrieved_before_accepting_conclusion(
    project, tmp_path, monkeypatch, proposed
):
    seen = []

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        seen.append(state)
        initial = state["unit_kind"] == "chunk" and state["round"] == 0
        selection = {
            "disposition": proposed if initial else "compliant",
            "support": state["chunk_id"]
            if initial and proposed == "violation"
            else "none",
            "next_request": next(
                c["id"]
                for c in state["candidate_menu"]
                if c["request"]["type"] == "GET_FILE"
            )
            if initial
            else "none_useful",
        }
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
    assert summary["policies"][0]["outcome"] == "compliant"
    assert summary["policies"][0]["findings"] == []
    assert len(seen) == 3
    assert any(e["type"] == "GET_FILE" for e in seen[1]["delivered_evidence"].values())
    assert verify_pack(pack)["validated_responses"] == 3


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
                        else "none_useful",
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
