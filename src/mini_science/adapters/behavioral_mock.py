from __future__ import annotations

"""Offline fixture adapter for testing mechanism sensitivity and failures."""

import json
import math
import re
import time
from typing import Any

from .base import LLMResponse, ProviderAdapter
from ..simulators import predict


SCENARIOS = frozenset({
    "constant",
    "transfer_sensitive",
    "transfer_ignored",
    "bad_stage1",
    "bad_final",
    "citation_leak",
})


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()), math.ceil(len(text) / 2)) if text else 0


class BehavioralMockAdapter(ProviderAdapter):
    """A deterministic, private-truth-free test fixture.

    It decides only from role text and the routed JSON visible in the request.
    It never opens world files and is always marked NON_EVIDENCE/TEST_FIXTURE.
    """

    def __init__(self, scenario: str = "constant") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown behavioral mock scenario: {scenario}")
        self.scenario = scenario
        self.model_name = f"behavioral-mock:{scenario}"
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _json_after_marker(text: str, marker: str) -> dict[str, Any]:
        index = text.find(marker)
        if index < 0:
            return {}
        candidate = text[index + len(marker):].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return {}

    def _final_payload(self, user: str) -> dict[str, Any] | str:
        if self.scenario == "bad_final":
            return '{"experiment_id":"E99","scientific_question":}'
        evidence = ["T01", "T02"]
        if self.scenario == "citation_leak":
            evidence.append("S01")
        selected = "E04"
        if self.scenario == "transfer_sensitive":
            routed = self._json_after_marker(user, "ROUTED INTERMEDIATE RECORD:")
            source_ids = routed.get("source_evidence_ids", []) if isinstance(routed, dict) else []
            selected = "E03" if source_ids and routed.get("status") != "controlled_misalignment" else "E01"
        elif self.scenario in {"transfer_ignored", "bad_stage1"}:
            selected = "E01"
        k_match = re.search(r"Nominal candidate-rate k=([0-9.]+)", user)
        experiment_match = re.search(r'"experiment_id":\s*"' + re.escape(selected) + r'",\s*"measure_t":\s*([0-9.]+),\s*"unit_cost":\s*[0-9.]+,\s*"x0":\s*([0-9.]+)', user)
        if k_match and experiment_match:
            k = float(k_match.group(1))
            measure_t = float(experiment_match.group(1))
            x0 = float(experiment_match.group(2))
            predicted_values = {model: round(predict(model, x0, measure_t, k), 6) for model in ("EXP_DECAY", "HYPERBOLIC_DECAY")}
        else:
            predicted_values = {"EXP_DECAY": 0.50, "HYPERBOLIC_DECAY": 0.40}
            measure_t = 2.6
            x0 = 0.7
        return {
            "experiment_id": selected,
            "scientific_question": "Which candidate mechanisms make the most different predictions under the selected measurement?",
            "hypotheses_to_discriminate": ["EXP_DECAY", "HYPERBOLIC_DECAY"],
            "predicted_values": predicted_values,
            "measurement": "normalized_state",
            "predicted_difference": "The candidate mechanisms predict different normalized states for the selected action.",
            "evidence_ids": evidence,
            "uncertainty": "moderate",
            "selected_action": {"experiment_id": selected, "x0": x0, "measure_t": measure_t},
        }

    def complete(self, messages: list[dict[str, str]], max_output_tokens: int) -> LLMResponse:
        started = time.monotonic()
        user = messages[-1]["content"] if messages else ""
        if "Role: cross-disciplinary pattern extractor" in user:
            if self.scenario == "bad_stage1":
                text = '{"shared_law_judgment":"unknown","candidate_law_id":"UNKNOWN"}'
            else:
                payload = {
                    "shared_law_judgment": "same",
                    "candidate_law_id": "EXP_DECAY",
                    "hypothesized_shared_law": "a decreasing decay-like relationship",
                    "source_evidence_ids": ["S01", "S02"],
                    "target_evidence_ids": ["T01", "T02"],
                    "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
                    "status": "supported_or_uncertain",
                    "brief_justification": f"The public records support a provisional structural match; fixture_call={len(self.calls)}.",
                }
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        elif "source_pattern JSON object" in user:
            text = json.dumps({"trend": "decreasing", "source_evidence_ids": ["S01", "S02"], "possible_mechanism_categories": ["decay-like"], "applicability_limits": "short record"}, ensure_ascii=False, sort_keys=True)
        elif "target_gap JSON object" in user:
            text = json.dumps({"unresolved_mechanism_pairs": [["EXP_DECAY", "HYPERBOLIC_DECAY"]], "target_evidence_ids": ["T01", "T02"], "candidate_interventions": ["longer measurement time"], "rationale": "The short record leaves candidates unresolved."}, ensure_ascii=False, sort_keys=True)
        elif "PROPOSAL_1:" in user:
            proposal_one = self._json_after_marker(user, "PROPOSAL_1:")
            proposal_two = self._json_after_marker(user, "PROPOSAL_2:")
            selected = "P1" if proposal_one.get("experiment_id") else ("P2" if proposal_two.get("experiment_id") else "P1")
            payload = self._final_payload(user)
            if isinstance(payload, str):
                text = payload
            else:
                payload["selected_proposer_id"] = selected
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        else:
            payload = self._final_payload(user)
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        response = LLMResponse(
            text=text,
            model=self.model_name,
            input_tokens=estimate_tokens(json.dumps(messages, ensure_ascii=False)),
            output_tokens=estimate_tokens(text),
            latency_ms=latency_ms,
            cost_usd=0.0,
            metadata={"provider": "behavioral-mock", "scenario": self.scenario, "non_evidence": True, "test_fixture": True, "usage_verified": True},
        )
        self.calls.append({"messages": json.loads(json.dumps(messages)), "max_output_tokens": max_output_tokens, "response": text})
        return response

    def audit_trace(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self.calls))
