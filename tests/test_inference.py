from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from jev_ci.errors import InferenceError
from jev_ci.inference import Gateway, response_telemetry, validate_answers


QUESTIONS = {"decision": {"type": "choice", "criteria": {"yes": "Yes", "no": "No"}}}


def payload(choice="yes"):
    return {
        "model": "typesafe-ai/jev",
        "answers": {
            "decision": {
                "type": "choice",
                "choice": choice,
                "probabilities": {"yes": 1.0, "no": 0.0},
            }
        },
    }


@pytest.mark.parametrize("choice", [[], {}, None, 1, True])
def test_untrusted_choice_types_are_controlled_errors(choice):
    with pytest.raises(InferenceError, match="selected choice"):
        validate_answers(payload(choice), QUESTIONS)


def test_routing_rejects_a_different_evaluator():
    response = payload()
    response["provider_metadata"] = {
        "gateway": {"routing": {"canonicalSlug": "another/model"}}
    }
    with pytest.raises(InferenceError, match="routing"):
        validate_answers(response, QUESTIONS)


def test_native_choice_preserves_a_tie_with_float_serialization_noise():
    response = payload()
    response["answers"]["decision"]["probabilities"] = {
        "yes": 0.49999999999999994,
        "no": 0.5,
    }
    answer = validate_answers(response, QUESTIONS)["decision"]
    assert answer["choice"] == "yes"
    assert answer["selected_probability"] == 0.49999999999999994
    response["answers"]["decision"]["probabilities"] = {"yes": 0.49999, "no": 0.50001}
    answer = validate_answers(response, QUESTIONS)["decision"]
    assert answer["choice"] == "yes"
    assert answer["choice_probability_mismatch"] is True
    assert answer["maximum_probability"] == 0.50001
    with pytest.raises(InferenceError, match="not a maximum"):
        validate_answers(response, QUESTIONS, legacy_maximum=True)


def test_declared_choice_is_authoritative_even_for_a_large_score_disagreement():
    answer = validate_answers(payload("no"), QUESTIONS)["decision"]
    assert answer["choice"] == "no"
    assert answer["selected_probability"] == 0
    assert answer["choice_probability_mismatch"] is True
    with pytest.raises(InferenceError, match="offered option"):
        validate_answers(payload("fabricated"), QUESTIONS)


def test_gateway_native_decimal_cost_and_routing_are_preserved():
    response = payload()
    metadata = {
        "gateway": {
            "cost": "0.000016674",
            "generationId": "fixture",
            "routing": {
                "finalProvider": "typesafe-ai",
                "canonicalSlug": "typesafe-ai/jev",
            },
        }
    }
    response["provider_metadata"] = metadata
    result = response_telemetry(response, {}, {})
    assert result["cost_usd"] == "0.000016674"
    assert result["cost_source"] == "provider_metadata.gateway.cost"
    assert result["provider_metadata"] == metadata
    response["provider_metadata"]["gateway"]["cost"] = "NaN"
    assert response_telemetry(response, {}, {})["cost_usd"] is None


def test_total_http_deadline_cancels_a_slow_stream(project):
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.02)
                yield b" "

    settings = project["config"]["inference"]
    events = []
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowBody()))
    start = time.monotonic()
    with pytest.raises(InferenceError, match="TimeoutError"):
        Gateway(settings, "fixture-key", transport=transport).evaluate(
            {}, QUESTIONS, start + 0.07, events.append
        )
    assert time.monotonic() - start < 0.3
    assert events[-1]["status"] == "transport_error"


def test_http_response_cap_stops_before_parsing(project):
    settings = {**project["config"]["inference"], "max_response_bytes": 32}
    events = []
    with pytest.raises(InferenceError, match="byte cap"):
        Gateway(
            settings,
            "fixture-key",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"x" * 100)
            ),
        ).evaluate({}, QUESTIONS, time.monotonic() + 1, events.append)
    assert events[-1]["status"] == "raw_output_incomplete"
