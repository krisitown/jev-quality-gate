"""Native TypeSafe choice transport with strict answer validation."""

from __future__ import annotations

import math
import time

import httpx

from .errors import InferenceError
from .util import canonical, digest, strict_json


def validate_answers(payload: object, questions: dict) -> dict:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("answers"), dict)
        or set(payload["answers"]) != set(questions)
    ):
        raise InferenceError("Jev answer IDs do not match questions")
    normalized = {}
    for name, question in questions.items():
        answer = payload["answers"][name]
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise InferenceError(f"{name}: expected choice answer")
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or set(probs) != set(question["criteria"]):
            raise InferenceError(f"{name}: probability keys do not match criteria")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (float, int))
            or not math.isfinite(v)
            or v < 0
            or v > 1
            for v in probs.values()
        ):
            raise InferenceError(f"{name}: invalid probabilities")
        if abs(sum(probs.values()) - 1) > 0.020000001:
            raise InferenceError(f"{name}: probabilities do not sum to one")
        choice = answer.get("choice")
        if choice not in probs or probs[choice] != max(probs.values()):
            raise InferenceError(f"{name}: selected choice is not a maximum")
        confidence = answer.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (float, int))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise InferenceError(f"{name}: invalid native confidence")
        normalized[name] = {
            "choice": choice,
            "selected_probability": float(probs[choice]),
            "probabilities": probs,
            "native_confidence": confidence,
        }
    returned = payload.get("model")
    if returned is not None and returned != "typesafe-ai/jev":
        raise InferenceError("Gateway returned a different model identity")
    return normalized


class Gateway:
    def __init__(
        self, settings: dict, key: str, *, transport: httpx.BaseTransport | None = None
    ):
        if not key:
            raise InferenceError("AI_GATEWAY_API_KEY is not configured")
        self.settings = settings
        self._key = key
        self._transport = transport

    def evaluate(
        self, state: dict, questions: dict, deadline: float, on_attempt
    ) -> tuple[dict, dict]:
        body = {"model": self.settings["model"], "state": state, "questions": questions}
        if not questions or len(questions) > self.settings["max_questions"]:
            raise InferenceError("Gateway question count exceeds cap")
        serialized = canonical(body)
        if self._key.encode() in serialized:
            raise InferenceError("credential appears in inference state")
        if len(serialized) > self.settings["max_request_bytes"]:
            raise InferenceError("Gateway request exceeds byte cap")
        for attempt in range(2):
            remaining = min(
                self.settings["timeout_seconds"], deadline - time.monotonic()
            )
            if remaining <= 0:
                raise InferenceError("Gateway deadline expired")
            on_attempt(
                {
                    "attempt": attempt + 1,
                    "request_bytes": len(serialized),
                    "status": "started",
                }
            )
            started = time.monotonic()
            try:
                with httpx.Client(
                    transport=self._transport, timeout=remaining, follow_redirects=False
                ) as client:
                    with client.stream(
                        "POST",
                        self.settings["endpoint"],
                        content=serialized,
                        headers={
                            "content-type": "application/json",
                            "accept": "application/json",
                            "authorization": f"Bearer {self._key}",
                        },
                    ) as response:
                        raw = bytearray()
                        for piece in response.iter_bytes():
                            raw.extend(piece)
                            if len(raw) > self.settings["max_response_bytes"]:
                                on_attempt(
                                    {
                                        "attempt": attempt + 1,
                                        "status": "raw_output_incomplete",
                                        "received_bytes": len(raw),
                                        "received_prefix_sha256": digest(
                                            bytes(
                                                raw[
                                                    : self.settings[
                                                        "max_response_bytes"
                                                    ]
                                                ]
                                            )
                                        ),
                                    }
                                )
                                raise InferenceError(
                                    "Gateway response exceeds byte cap"
                                )
                        status = response.status_code
                        routing = {
                            key: value.replace(self._key, "[REDACTED]")
                            for key, value in response.headers.items()
                            if key.lower()
                            in {
                                "x-vercel-ai-gateway-request-id",
                                "x-vercel-ai-gateway-provider",
                                "x-vercel-ai-gateway-model",
                            }
                        }
            except httpx.HTTPError as exc:
                on_attempt(
                    {
                        "attempt": attempt + 1,
                        "status": "transport_error",
                        "error_type": type(exc).__name__,
                        "elapsed_seconds": time.monotonic() - started,
                    }
                )
                raise InferenceError(
                    f"Gateway transport failed: {type(exc).__name__}"
                ) from exc
            event = {
                "attempt": attempt + 1,
                "http_status": status,
                "response_bytes": len(raw),
                "elapsed_seconds": time.monotonic() - started,
                "routing": routing,
            }
            response_redacted = self._key.encode() in raw
            safe_raw = bytes(raw).replace(self._key.encode(), b"[REDACTED]")
            on_attempt(
                {
                    **event,
                    "status": "received",
                    "raw_body": safe_raw,
                    "credential_redacted": response_redacted,
                }
            )
            if status == 503 and attempt == 0:
                on_attempt({**event, "status": "retry_503"})
                if deadline - time.monotonic() <= 0.5:
                    raise InferenceError("Gateway 503 and deadline exhausted")
                time.sleep(0.5)
                continue
            if status != 200:
                on_attempt({**event, "status": "http_error"})
                raise InferenceError(f"Gateway returned HTTP {status}")
            try:
                payload = strict_json(raw)
            except (ValueError, UnicodeError) as exc:
                on_attempt({**event, "status": "invalid_json"})
                raise InferenceError("Gateway returned malformed JSON") from exc
            answers = validate_answers(payload, questions)
            if response_redacted:
                payload = strict_json(safe_raw)
            safe = {
                "usage": payload.get("usage"),
                "cost": payload.get("cost"),
                "model": payload.get("model"),
                "routing": routing,
                "attempt": event,
            }
            safe["credential_redacted_from_response"] = response_redacted
            on_attempt(
                {
                    **event,
                    "status": "validated",
                    "usage": safe["usage"],
                    "cost": safe["cost"],
                    "model": safe["model"],
                }
            )
            return answers, {"raw_response": payload, "telemetry": safe}
        raise InferenceError("Gateway 503 retry exhausted")
