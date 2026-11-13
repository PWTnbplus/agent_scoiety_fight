from __future__ import annotations

import json
import shutil
from pathlib import Path

from mini_science.authorization import V5P4_CONFIRMATION_PHRASE, create_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.real_gate import V5P4SessionGate
from mini_science.runner import _execute_stage1, _real_result_failure_reason
from mini_science.adapters.base import LLMResponse


class FakePaidAdapter:
    model_name = "kimi-k2.6"
    input_cost_per_1k = 0.00095
    output_cost_per_1k = 0.004

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, messages, max_output_tokens):
        self.calls += 1
        text = json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
        return LLMResponse(text=text, model=self.model_name, input_tokens=100, output_tokens=80, latency_ms=1, cost_usd=0.001, metadata={"returned_model": self.model_name, "usage_verified": True, "finish_reason": "stop"})


def _stage1_payload(**overrides):
    payload = {
        "shared_law_judgment": "same",
        "candidate_law_id": "EXP_DECAY",
        "hypothesized_shared_law": "decreasing decay-like relationship",
        "source_evidence_ids": ["S01", "S02"],
        "target_evidence_ids": ["T01", "T02"],
        "variable_mapping": {"source_state": "target_state", "source_time": "target_time"},
        "status": "supported_or_uncertain",
        "brief_justification": "public observations support a provisional structural comparison",
    }
    payload.update(overrides)
    return payload


def _run_stage1_failure(tmp_path: Path, payload: dict) -> tuple[dict, str | None, FakePaidAdapter, V5P4SessionGate]:
    root = tmp_path / "project"
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(source_root / "data" / "worlds_v5p4_dev", root / "data" / "worlds_v5p4_dev")
    shutil.copytree(source_root / "private" / "worlds_v5p4_dev", root / "private" / "worlds_v5p4_dev")
    config = load_config("config/v5p4_offline_dev.json")
    plan = pilot_request_plan(root, config, worlds=["CV001"], conditions=list(config.conditions), repeats=1)
    auth = create_v5p4_authorization(root, config, approved_by="user_explicit", confirmation=V5P4_CONFIRMATION_PHRASE, authorization_note="offline fail-fast fixture", request_plan=plan, worlds=["CV001"], conditions=list(config.conditions), max_unique_provider_attempts=5, max_estimated_cost_usd=0.05)
    gate = V5P4SessionGate(root, auth.parent)
    adapter = FakePaidAdapter(payload)
    run_dir = root / "runs" / "failfast"
    events = run_dir / "events.jsonl"
    ledger = run_dir / "call_ledger.jsonl"
    cache, _, reason = _execute_stage1(project_root=root, config=config, run_dir_path=run_dir, adapter=adapter, events_path=events, ledger_path=ledger, run_id="failfast", world_id="CV001", replicate=0, owner="C_SEQ2_TRANSFER", pair_id="CV001_R0", attempt_counts={}, real_gate=gate, provider="kimi26", is_real_provider=True)
    return cache, reason, adapter, gate


def test_e04_in_stage1_is_rejected_before_downstream_calls(tmp_path):
    cache, reason, adapter, gate = _run_stage1_failure(tmp_path, _stage1_payload(brief_justification="choose E04 now"))
    assert cache["valid"] is True
    assert reason == "stage1_action_oracle_leak"
    assert adapter.calls == 1
    assert gate.summary()["calls_used"] == 1


def test_invalid_stage1_mapping_is_scientific_failure_not_safety_abort(tmp_path):
    cache, reason, adapter, gate = _run_stage1_failure(tmp_path, _stage1_payload(variable_mapping={"source_concentration": "target_state", "source_minutes": "target_time"}))
    assert cache["valid"] is False
    assert reason is None
    assert adapter.calls == 1
    assert gate.summary()["calls_used"] == 1


def test_numeric_failure_is_a_separate_paid_fail_fast_reason():
    row = {"valid": True, "prediction_consistency": "FAIL", "mapping_valid": True}
    assert _real_result_failure_reason(row) == "stage2_numeric_consistency_failure"
