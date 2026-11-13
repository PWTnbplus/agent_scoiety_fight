from __future__ import annotations

from typing import Callable

from ..adapters.base import LLMResponse
from ..prompts import compete_judge_messages, compete_proposer_messages
from ..schema import WorldPublicView, parse_json_object, validate_final_question, validate_judge_choice


def _as_dict(response: LLMResponse) -> dict:
    parsed = parse_json_object(response.text)
    return parsed.data if parsed.valid and parsed.data is not None else {"invalid_proposal": parsed.reason}


def run(view: WorldPublicView, call: Callable[[str, list[dict[str, str]], int], LLMResponse]) -> dict[str, LLMResponse | dict]:
    proposer_one = call("proposer_1", compete_proposer_messages(view, "P1"), 300)
    proposer_two = call("proposer_2", compete_proposer_messages(view, "P2"), 300)
    judge = call("evidence_judge", compete_judge_messages(view, _as_dict(proposer_one), _as_dict(proposer_two)), 300)
    proposal_one = _as_dict(proposer_one)
    proposal_two = _as_dict(proposer_two)
    return {"proposer_one": proposer_one, "proposer_two": proposer_two, "final_response": judge, "proposal_one": proposal_one, "proposal_two": proposal_two, "judge_contract": validate_judge_choice(judge.text, proposal_one, proposal_two, view)}
