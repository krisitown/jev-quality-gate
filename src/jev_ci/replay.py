"""Integrity, protocol evidence linkage, and deterministic aggregate checks."""

from __future__ import annotations

import json
from pathlib import Path

from .errors import TraceError
from .trace import inspect_pack
from .util import digest


def _verify_attempt_outcomes(
    attempts: list[tuple[int, dict]], unit_id: str, *, allow_retry_tail: bool = False
) -> None:
    by_number: dict[int, list[str]] = {}
    for _, payload in attempts:
        number = payload.get("attempt")
        status = payload.get("status")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise TraceError(f"gateway attempt number malformed: {unit_id}")
        by_number.setdefault(number, []).append(status)
    if sorted(by_number) != list(range(1, len(by_number) + 1)):
        raise TraceError(f"gateway attempt numbering differs: {unit_id}")
    terminal = {
        "validated",
        "http_error",
        "invalid_json",
        "invalid_answers",
        "transport_error",
        "raw_output_incomplete",
        "retry_503",
    }
    for number, statuses in by_number.items():
        if not statuses or statuses[0] != "started" or statuses.count("started") != 1:
            raise TraceError(f"gateway attempt start differs: {unit_id}")
        endings = [status for status in statuses[1:] if status in terminal]
        if len(endings) != 1 or sum(status == "received" for status in statuses) > 1:
            raise TraceError(f"gateway attempt completion differs: {unit_id}")
        ending = endings[0]
        if (
            ending
            in {
                "validated",
                "http_error",
                "invalid_json",
                "invalid_answers",
                "retry_503",
            }
            and statuses.count("received") != 1
        ):
            raise TraceError(f"gateway attempt response event missing: {unit_id}")
        if ending in {"transport_error", "raw_output_incomplete"} and statuses.count(
            "received"
        ):
            raise TraceError(f"gateway attempt transport sequence differs: {unit_id}")
        if ending == "retry_503" and number == len(by_number) and not allow_retry_tail:
            raise TraceError(f"gateway retry has no following attempt: {unit_id}")
        if ending == "validated" and number != len(by_number):
            raise TraceError(f"gateway attempt continued after validation: {unit_id}")


def _verify_protocol_links(path: Path, records: list[dict], summary: dict) -> None:
    """Check that saved rounds are backed by one ordered request/attempt/response chain."""
    if any(row.get("run_id") != summary.get("run_id") for row in records):
        raise TraceError("Evidence Pack event run ID differs")
    if (
        records[0].get("type") != "run_started"
        or records[-1].get("type") != "run_finished"
    ):
        raise TraceError("Evidence Pack run boundaries incomplete")
    if records[0].get("payload", {}).get("run_id") != summary.get("run_id"):
        raise TraceError("Evidence Pack start run ID differs")
    if records[-1].get("payload", {}).get("status") != summary.get("status") or records[
        -1
    ].get("payload", {}).get("exit_code") != summary.get("exit_code"):
        raise TraceError("Evidence Pack terminal outcome differs")

    events_by_unit: dict[str, list[tuple[int, dict]]] = {}
    responses: list[dict] = []
    for index, row in enumerate(records):
        unit_id = row.get("evaluation_id")
        if unit_id:
            events_by_unit.setdefault(unit_id, []).append((index, row))
        if row.get("type") == "model_response":
            responses.append(row)

    results: dict[str, dict] = {}
    for result_path in (path / "evaluations").glob("*/result.json"):
        result = json.loads(result_path.read_bytes())
        unit_id = result.get("id")
        if not unit_id or unit_id in results or result_path.parent.name != unit_id:
            raise TraceError("Evidence Pack evaluation result identity differs")
        results[unit_id] = result

    response_keys: set[tuple[str, int]] = set()
    for unit_id, result in results.items():
        unit_events = events_by_unit.get(unit_id, [])
        rounds = result.get("rounds", [])
        if not isinstance(rounds, list):
            raise TraceError("Evidence Pack saved rounds are malformed")
        prompts = [(i, e) for i, e in unit_events if e.get("type") == "prompt_sent"]
        unit_responses = [
            (i, e) for i, e in unit_events if e.get("type") == "model_response"
        ]
        attempts = [
            (i, e) for i, e in unit_events if e.get("type") == "gateway_attempt"
        ]
        finished = [
            (i, e) for i, e in unit_events if e.get("type") == "evaluation_finished"
        ]
        if len(finished) != 1:
            raise TraceError(
                f"evaluation finish event missing or duplicated: {unit_id}"
            )
        finish_payload = finished[0][1].get("payload", {})
        for key in ("outcome", "reason", "calls"):
            if key in finish_payload and finish_payload[key] != result.get(key):
                raise TraceError(
                    f"evaluation result differs from finish event: {unit_id}"
                )

        if not rounds:
            # Operational failures can happen before a request is persisted, or after its
            # attempts. They have no saved model response/round to replay.
            if unit_responses:
                raise TraceError(f"orphan model response: {unit_id}")
            error_events = [
                (i, e)
                for i, e in unit_events
                if e.get("type") in {"inference_error", "provider_error"}
            ]
            for prompt_index, prompt in prompts:
                later_attempts = [
                    event
                    for index, event in attempts
                    if index > prompt_index
                    and event.get("payload", {}).get("attempt") is not None
                ]
                if (
                    not later_attempts
                    and not error_events
                    and not result.get("operational_error")
                ):
                    raise TraceError(f"orphan failed prompt: {unit_id}")
                if any(
                    event.get("payload", {}).get("status") == "validated"
                    for event in later_attempts
                ):
                    raise TraceError(
                        f"validated response missing from saved rounds: {unit_id}"
                    )
            if sum(
                e.get("payload", {}).get("status") == "started" for _, e in attempts
            ) != result.get("calls"):
                raise TraceError(f"evaluation call count differs: {unit_id}")
            continue
        if len(rounds) > len(prompts) or len(rounds) != len(unit_responses):
            raise TraceError(f"saved round prompt/response count differs: {unit_id}")
        if len(finished) != 1 or finished[0][0] <= unit_responses[-1][0]:
            raise TraceError(f"evaluation event ordering differs: {unit_id}")
        used_prompts: set[int] = set()
        started_count = sum(
            e.get("payload", {}).get("status") == "started" for _, e in attempts
        )
        for saved in rounds:
            number = saved.get("round")
            key = (unit_id, number)
            if key in response_keys:
                raise TraceError(f"duplicate saved round: {unit_id}")
            response_keys.add(key)
            matched_prompts = [
                (i, e)
                for i, e in prompts
                if e.get("payload", {}).get("round") == number
            ]
            matched_responses = [
                (i, e)
                for i, e in unit_responses
                if e.get("payload", {}).get("round") == number
            ]
            if len(matched_prompts) != 1 or len(matched_responses) != 1:
                raise TraceError(
                    f"saved round prompt/response linkage differs: {unit_id}"
                )
            pi, prompt = matched_prompts[0]
            ri, response = matched_responses[0]
            pp, rp = prompt.get("payload", {}), response.get("payload", {})
            for event in (prompt, response):
                if (
                    event.get("evaluation_id") != unit_id
                    or event.get("policy_id") != result.get("policy_id")
                    or event.get("chunk_id") != result.get("chunk_id")
                ):
                    raise TraceError(f"event evaluation linkage differs: {unit_id}")
            used_prompts.add(pi)
            if (
                pi >= ri
                or pp.get("request_blob") != saved.get("request_blob")
                or rp.get("request_blob") != saved.get("request_blob")
                or rp.get("response_blob") != saved.get("response_blob")
                or rp.get("validated") != saved.get("answers")
            ):
                raise TraceError(f"saved round payload linkage differs: {unit_id}")
            request = json.loads(
                (path / "blobs" / "sha256" / saved["request_blob"]).read_bytes()
            )
            state = request.get("state", {})
            if (
                state.get("round") != number
                or state.get("policy", {}).get("id") != result.get("policy_id")
                or state.get("chunk_id") != result.get("chunk_id")
                or state.get("unit_kind") != result.get("unit_kind")
            ):
                raise TraceError(f"saved request state linkage differs: {unit_id}")
            round_attempts = [
                (i, e.get("payload", {})) for i, e in attempts if pi < i < ri
            ]
            statuses = [p.get("status") for _, p in round_attempts]
            if (
                statuses.count("started") < 1
                or statuses.count("validated") != 1
                or statuses.index("validated") < statuses.index("started")
            ):
                raise TraceError(f"successful round gateway attempts differ: {unit_id}")
            attempt_numbers = [
                p.get("attempt")
                for _, p in round_attempts
                if p.get("status") == "started"
            ]
            if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
                raise TraceError(f"gateway attempt numbering differs: {unit_id}")
            _verify_attempt_outcomes(round_attempts, unit_id)
        if len(used_prompts) != len(rounds):
            raise TraceError(f"saved round prompt linkage differs: {unit_id}")
        # A failed request may follow one or more saved rounds. It is evidenced by the
        # operational error marker and completed gateway attempts, but has no response.
        tail_prompts = [(i, e) for i, e in prompts if i not in used_prompts]
        if tail_prompts and not result.get("operational_error"):
            raise TraceError(f"orphan failed prompt: {unit_id}")
        for prompt_index, _ in tail_prompts:
            next_prompt = min(
                (i for i, _ in prompts if i > prompt_index), default=len(records)
            )
            tail_attempts = [
                (i, e.get("payload", {}))
                for i, e in attempts
                if prompt_index < i < next_prompt
            ]
            if not tail_attempts or any(
                p.get("status") == "validated" for _, p in tail_attempts
            ):
                raise TraceError(f"failed prompt attempt evidence differs: {unit_id}")
            _verify_attempt_outcomes(tail_attempts, unit_id, allow_retry_tail=True)
        if started_count != result.get("calls"):
            raise TraceError(f"evaluation call count differs: {unit_id}")

    if len(response_keys) != len(responses):
        raise TraceError("orphan or duplicate model response event")


def _verify_diagnostics(path: Path, summary: dict) -> None:
    if "diagnostics" not in summary:
        return
    expected = []
    for policy in summary.get("policies", []):
        unit_ids = list(policy.get("completed_units", []))
        if policy.get("reconciliation_id"):
            unit_ids.append(policy["reconciliation_id"])
        for unit_id in unit_ids:
            result = json.loads(
                (path / "evaluations" / unit_id / "result.json").read_bytes()
            )
            if result.get("outcome") != "compliant":
                expected.append(
                    {
                        "policy_id": result.get("policy_id"),
                        "unit_id": result.get("id"),
                        "unit_kind": result.get("unit_kind"),
                        "chunk_id": result.get("chunk_id"),
                        "outcome": result.get("outcome"),
                        "reason": result.get("reason"),
                        "calls": result.get("calls"),
                    }
                )
    if summary["diagnostics"] != expected:
        raise TraceError("replayed unit diagnostics differ")


def verify_pack(path: Path) -> dict:
    try:
        checksums = json.loads((path / "checksums.json").read_bytes())["files"]
        actual = {
            file.relative_to(path).as_posix(): digest(file.read_bytes())
            for file in path.rglob("*")
            if file.is_file() and file.name != "checksums.json"
        }
        if actual != checksums:
            raise TraceError("Evidence Pack checksum mismatch")
        blob_manifest = json.loads((path / "blobs" / "manifest.json").read_bytes())[
            "blobs"
        ]
        for sha, metadata in blob_manifest.items():
            content = (path / "blobs" / "sha256" / sha).read_bytes()
            if digest(content) != sha or len(content) != metadata["bytes"]:
                raise TraceError("Evidence Pack blob identity mismatch")
        records = [
            json.loads(line)
            for line in (path / "events.jsonl").read_bytes().splitlines()
        ]
        if (
            not records
            or records[-1]["type"] != "run_finished"
            or [row["sequence"] for row in records] != list(range(1, len(records) + 1))
        ):
            raise TraceError("Evidence Pack event sequence incomplete")
        from .inference import validate_answers
        from .errors import InferenceError

        count = 0
        for row in records:
            if row["type"] == "model_response":
                request = json.loads(
                    (
                        path / "blobs" / "sha256" / row["payload"]["request_blob"]
                    ).read_bytes()
                )
                response = json.loads(
                    (
                        path / "blobs" / "sha256" / row["payload"]["response_blob"]
                    ).read_bytes()
                )
                try:
                    replayed_answers = validate_answers(response, request["questions"])
                except InferenceError as exc:
                    raise TraceError(
                        f"replayed typed answers are invalid: {exc}"
                    ) from exc
                if replayed_answers != row["payload"]["validated"]:
                    raise TraceError("replayed typed answers differ")
                count += 1
        summary = inspect_pack(path)
        if summary.get("run_id") != records[-1].get("run_id"):
            raise TraceError("Evidence Pack summary run ID differs")
        _verify_protocol_links(path, records, summary)
        _verify_diagnostics(path, summary)
        if summary["status"] != records[-1]["payload"]["status"]:
            raise TraceError("replayed status differs")
        replayed_aggregates = 0
        if (path / "policies" / "manifest.json").exists() and summary.get("policies"):
            from .aggregation import aggregate, run_status
            from .policy import Policy, parse_policy_yaml

            policy_manifest = json.loads(
                (path / "policies" / "manifest.json").read_bytes()
            )
            config_sha = json.loads((path / "manifest.json").read_bytes())[
                "config_sha256"
            ]
            config = json.loads((path / "blobs" / "sha256" / config_sha).read_bytes())
            by_id = {item["id"]: item for item in policy_manifest["files"]}
            for stored in summary["policies"]:
                entry = by_id[stored["policy_id"]]
                raw = (path / "blobs" / "sha256" / entry["raw_sha256"]).read_bytes()
                policy = Policy(entry["path"], raw, parse_policy_yaml(raw))
                units = [
                    json.loads(
                        (path / "evaluations" / unit_id / "result.json").read_bytes()
                    )
                    for unit_id in stored["completed_units"]
                ]
                recon = (
                    json.loads(
                        (
                            path
                            / "evaluations"
                            / stored["reconciliation_id"]
                            / "result.json"
                        ).read_bytes()
                    )
                    if stored["reconciliation_id"]
                    else None
                )
                actual = aggregate(
                    policy,
                    units,
                    recon,
                    stored["expected_chunks"],
                    stored["unsupported_content"],
                    stored["incomplete_coverage"],
                    reason_version=stored.get("reason_version", 1),
                )
                if (
                    actual["outcome"] == "uncertain"
                    and config["ci"]["incomplete"] == "block"
                ):
                    actual["action"] = "block"
                if actual != stored or actual != json.loads(
                    (path / "policies" / policy.id / "aggregate.json").read_bytes()
                ):
                    raise TraceError(f"replayed aggregate differs: {policy.id}")
                replayed_aggregates += 1
            status, code = run_status(summary["policies"], summary["errors"])
            if config["mode"] == "calibration" and status == "blocked":
                status, code = "completed_with_findings", 0
            if status != summary["status"] or code != summary["exit_code"]:
                raise TraceError("replayed CI outcome differs")
        return {
            "status": "verified",
            "verification_scope": "integrity_linkage_and_deterministic_aggregation",
            "validated_responses": count,
            "replayed_aggregates": replayed_aggregates,
            "run_status": summary["status"],
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TraceError(f"protocol replay failed: {exc}") from exc
