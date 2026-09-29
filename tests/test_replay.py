from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from jev_ci.coordinator import evaluate
from jev_ci.errors import TraceError
from jev_ci.trace import verify_pack


def _answer(question: dict, selection: str) -> dict:
    return {
        "type": "choice",
        "choice": selection,
        "probabilities": {key: float(key == selection) for key in question["criteria"]},
        "confidence": 0.9,
    }


@pytest.fixture
def successful_pack(project, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "replay-test-key")

    def mock(request):
        body = json.loads(request.content)
        answers = {
            name: _answer(
                question,
                "uncertain"
                if name == "disposition"
                else "none"
                if name == "support"
                else "none_useful",
            )
            for name, question in body["questions"].items()
        }
        return httpx.Response(200, json={"answers": answers})

    output = tmp_path / "pack"
    evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(mock),
    )
    return output


def _reseal(pack):
    files = {
        file.relative_to(pack).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(pack.rglob("*"))
        if file.is_file() and file.name != "checksums.json"
    }
    (pack / "checksums.json").write_text(
        json.dumps({"schema_version": "jev.checksums/0.1", "files": files})
    )


def _events(pack):
    return [
        json.loads(line) for line in (pack / "events.jsonl").read_text().splitlines()
    ]


def _save_events(pack, records):
    (pack / "events.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in records
        )
    )
    _reseal(pack)


def test_replay_accepts_linked_rounds(successful_pack):
    assert verify_pack(successful_pack)["status"] == "verified"


def test_replay_checks_diagnostics_derived_from_saved_units(successful_pack):
    summary_file = successful_pack / "summary.json"
    summary = json.loads(summary_file.read_text())
    assert summary["diagnostics"]
    summary["diagnostics"][0]["reason"] = "fabricated_reason"
    summary_file.write_text(json.dumps(summary))
    _reseal(successful_pack)
    with pytest.raises(TraceError, match="unit diagnostics"):
        verify_pack(successful_pack)


def test_replay_accepts_older_summary_without_diagnostics(successful_pack):
    summary_file = successful_pack / "summary.json"
    summary = json.loads(summary_file.read_text())
    summary.pop("diagnostics", None)
    summary_file.write_text(json.dumps(summary))
    _reseal(successful_pack)
    assert verify_pack(successful_pack)["status"] == "verified"


def test_replay_rejects_deleted_response_event(successful_pack):
    records = _events(successful_pack)
    records = [row for row in records if row["type"] != "model_response"]
    for sequence, row in enumerate(records, 1):
        row["sequence"] = sequence
    _save_events(successful_pack, records)
    with pytest.raises(TraceError, match="checksum|prompt/response count"):
        verify_pack(successful_pack)


def test_replay_rejects_changed_saved_round_reference(successful_pack):
    result_file = next((successful_pack / "evaluations").glob("*/result.json"))
    result = json.loads(result_file.read_text())
    result["rounds"][0]["response_blob"] = result["rounds"][0]["request_blob"]
    result_file.write_text(json.dumps(result))
    _reseal(successful_pack)
    with pytest.raises(TraceError, match="payload linkage"):
        verify_pack(successful_pack)


def test_replay_rejects_removed_gateway_attempt(successful_pack):
    records = _events(successful_pack)
    removed = False
    kept = []
    for row in records:
        if (
            row["type"] == "gateway_attempt"
            and row["payload"]["status"] == "validated"
            and not removed
        ):
            removed = True
            continue
        kept.append(row)
    assert removed
    for sequence, row in enumerate(kept, 1):
        row["sequence"] = sequence
    _save_events(successful_pack, kept)
    with pytest.raises(TraceError, match="gateway attempts"):
        verify_pack(successful_pack)


@pytest.mark.parametrize("failure", ["authentication", "invalid_answers"])
def test_replay_accepts_saved_round_followed_by_gateway_error(
    project, tmp_path, monkeypatch, failure
):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "replay-test-key")

    def mock(request):
        body = json.loads(request.content)
        state = body["state"]
        if state["round"] == 1:
            if failure == "invalid_answers":
                return httpx.Response(200, json={"answers": {}})
            return httpx.Response(401, json={"error": "unauthorized"})
        selections = {
            "disposition": "need_more_evidence",
            "support": "none",
            "next_request": next(
                item["id"]
                for item in state["candidate_menu"]
                if item["request"]["type"] == "GET_FILE"
            ),
        }
        answers = {
            name: _answer(question, selections.get(name, "none_useful"))
            for name, question in body["questions"].items()
        }
        return httpx.Response(200, json={"answers": answers})

    output = tmp_path / "partial-error-pack"
    evaluate(
        project["repo"],
        "feature",
        "main",
        project["config_path"],
        project["policies"],
        output,
        transport=httpx.MockTransport(mock),
    )
    result = json.loads(
        next((output / "evaluations").glob("*/result.json")).read_text()
    )
    assert result["rounds"]
    assert result["operational_error"]
    assert verify_pack(output)["status"] == "verified"
