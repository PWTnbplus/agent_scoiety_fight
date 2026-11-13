from __future__ import annotations

from typing import Callable

from ..adapters.base import LLMResponse
from ..prompts import seq2_stage1_messages, seq2_stage2_messages
from ..router import route_shared_law_artifact
from ..schema import WorldPublicView, ValidationResult, parse_json_object, validate_shared_law


def extract_stage1(view: WorldPublicView, call: Callable[[str, list[dict[str, str]], int], LLMResponse]) -> tuple[LLMResponse, ValidationResult]:
    response = call("pattern_extractor", seq2_stage1_messages(view), 450)
    validation = validate_shared_law(response.text, view)
    if validation.valid and validation.data is not None:
        return response, validation
    neutral = {
        "shared_law_judgment": "unknown",
        "candidate_law_id": "UNKNOWN",
        "hypothesized_shared_law": "invalid stage-1 output",
        "source_evidence_ids": [],
        "target_evidence_ids": [],
        "variable_mapping": {},
        "status": "invalid",
        "brief_justification": "Stage-1 output failed schema validation.",
    }
    return response, ValidationResult(False, validation.reason, neutral)


def run_stage2(
    view: WorldPublicView,
    condition: str,
    artifact: dict,
    transfer_applied: bool,
    call: Callable[[str, list[dict[str, str]], int], LLMResponse],
) -> tuple[LLMResponse, dict]:
    route = route_shared_law_artifact(artifact, transfer_applied)
    response = call("question_designer", seq2_stage2_messages(view, route["artifact"], condition), 450)
    return response, route
