"""Small library seam for evaluators sharing the bounded controller contract."""

from __future__ import annotations

from typing import Callable, Protocol


class Evaluator(Protocol):
    @property
    def identity(self) -> dict:
        """Actual adapter/model identity, recorded separately from root config."""
        ...

    def request_bytes(self, state: dict, questions: dict) -> int:
        """Size of the complete encoded request, including transport wrappers."""
        ...

    def evaluate(
        self,
        state: dict,
        questions: dict,
        deadline: float,
        on_attempt: Callable[[dict], None],
    ) -> tuple[dict, dict]:
        """Validate offered choices and return normalized answers plus raw telemetry.

        Answers contain choice and selected_probability (nullable when unavailable).
        Response contains raw_response and telemetry. Attempt events use the same
        started/received/validated/error lifecycle as the native adapter. Unavailable
        scores or costs must remain null; a future LLM must not invent probabilities.
        """
        ...


def meets_threshold(answer: dict, threshold: float | None) -> bool:
    """An absent score cannot satisfy a configured score threshold."""
    score = answer.get("selected_probability")
    return threshold is None or (score is not None and score >= threshold)
