from __future__ import annotations

import json
import math
import time
from typing import Any

from .base import LLMResponse, ProviderAdapter


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()), math.ceil(len(text) / 2)) if text else 0


class MockAdapter(ProviderAdapter):
    """Deterministic fixed-output adapter; it never reads private truth."""

    model_name = "mock-provider"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        started = time.monotonic()
        user = messages[-1]["content"] if messages else ""
        if "Role: cross-disciplinary pattern extractor" in user:
            payload: dict[str, Any] = {
                "shared_law_judgment": "unknown",
                "candidate_law_id": "UNKNOWN",
                "hypothesized_shared_law": "a possible monotone decay pattern under rescaling",
                "source_evidence_ids": ["S01", "S02"],
                "target_evidence_ids": ["T01", "T02"],
                "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
                "status": "supported_or_uncertain",
                "brief_justification": "The short public records are compatible with a shared decreasing shape, but the mechanism remains uncertain.",
            }
        elif "source_pattern JSON object" in user:
            payload = {"trend": "decreasing normalized state", "source_evidence_ids": ["S01", "S02"], "possible_mechanism_categories": ["decay-like"], "applicability_limits": "short synthetic record"}
        elif "target_gap JSON object" in user:
            payload = {"unresolved_mechanism_pairs": [["EXP_DECAY", "HYPERBOLIC_DECAY"]], "target_evidence_ids": ["T01", "T02"], "candidate_interventions": ["longer measurement time", "larger initial state"], "rationale": "The initial short observations do not fully separate candidate curves."}
        else:
            payload = {
                "experiment_id": "E04",
                "scientific_question": "Which candidate mechanisms make the most different normalized-state predictions at a longer measurement time?",
                "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
                "measurement": "normalized_state",
                "predicted_difference": "The two candidate curves predict different normalized states for the selected action.",
                "evidence_ids": ["T01", "T02", "S01"],
                "uncertainty": "moderate",
            }
            if "selected_proposer_id" in user or "evidence judge" in user.lower():
                payload["selected_proposer_id"] = "P1"
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        self.calls.append({"messages": json.loads(json.dumps(messages)), "max_output_tokens": max_output_tokens, "response": text})
        return LLMResponse(text=text, model=self.model_name, input_tokens=estimate_tokens(json.dumps(messages, ensure_ascii=False)), output_tokens=estimate_tokens(text), latency_ms=latency_ms, cost_usd=0.0, metadata={"provider": "mock", "non_evidence": True})

    def audit_trace(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self.calls))
