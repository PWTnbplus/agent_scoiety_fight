from __future__ import annotations

from typing import Callable

from ..adapters.base import LLMResponse
from ..prompts import collab_source_messages, collab_synthesis_messages, collab_target_messages
from ..schema import WorldPublicView, parse_json_object


def _as_dict(response: LLMResponse) -> dict:
    parsed = parse_json_object(response.text)
    return parsed.data if parsed.valid and parsed.data is not None else {"invalid_intermediate": parsed.reason}


def run(view: WorldPublicView, call: Callable[[str, list[dict[str, str]], int], LLMResponse]) -> dict[str, LLMResponse | dict]:
    source = call("source_analyst", collab_source_messages(view), 300)
    target = call("target_analyst", collab_target_messages(view), 300)
    synthesis = call("synthesis_designer", collab_synthesis_messages(view, _as_dict(source), _as_dict(target)), 300)
    return {"source_response": source, "target_response": target, "final_response": synthesis, "source_artifact": _as_dict(source), "target_artifact": _as_dict(target)}
