from __future__ import annotations

from typing import Callable

from ..adapters.base import LLMResponse
from ..prompts import single_messages
from ..schema import WorldPublicView


def run(view: WorldPublicView, condition: str, call: Callable[[str, list[dict[str, str]], int], LLMResponse], *, protocol_version: str = "v4") -> dict[str, LLMResponse | str]:
    response = call("single_question_designer", single_messages(view, condition, protocol_version=protocol_version), 900)
    return {"final_response": response, "final_raw": response.text}
