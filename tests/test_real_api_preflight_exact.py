from __future__ import annotations

from dataclasses import replace

import pytest

from mini_science.authorization import CONFIRMATION_PHRASE, create_authorization
from mini_science.budget_plan import check_api_request_plan, pilot_request_plan, probe_request_plan
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, PersistentRealGate


def _config():
    return replace(load_config("config/real_gate_v3.json"), allowed_worlds=("W001",), allowed_conditions=("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"))


def _authorize(tmp_path, config, calls=8, cost=0.10):
    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["pilot", "check-api", "probe-role"], worlds=["W001"], conditions=list(config.allowed_conditions), max_unique_provider_attempts=calls, max_estimated_cost_usd=cost, confirmation=CONFIRMATION_PHRASE, authorization_note="offline test")


def test_real_api_preflight_uses_actual_prompt_shapes_and_five_g3_requests():
    config = _config()
    plan = pilot_request_plan(".", config, worlds=["W001"], conditions=list(config.allowed_conditions), repeats=1)
    assert len(plan) == 5
    assert {row["max_output_tokens"] for row in plan if row["agent_name"] == "single_question_designer"} == {900}
    assert {row["max_output_tokens"] for row in plan if row["agent_name"] in {"pattern_extractor", "question_designer"}} == {450}
    assert all(row["input_token_upper_bound"] >= row["prompt_input_tokens"] > 0 for row in plan)
    assert all("hidden_truth" not in json_text for row in plan for json_text in [str(row)])
    assert len(check_api_request_plan(max_output_tokens=64)) == 1
    assert probe_request_plan(".", config, world_id="W001", role="pattern_extractor", max_output_tokens=800)[0]["prompt_input_tokens"] > 0


def test_real_api_preflight_rejects_entire_plan_before_transport(tmp_path):
    config = _config()
    _authorize(tmp_path, config, calls=4, cost=0.10)
    gate = PersistentRealGate(tmp_path, config)
    plan = pilot_request_plan(".", config, worlds=["W001"], conditions=list(config.allowed_conditions), repeats=1)
    with pytest.raises(GateDenied):
        gate.preflight(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", request_plan=plan, worlds=["W001"], conditions=list(config.allowed_conditions))
    assert not (tmp_path / "runs" / "v3_real_gate_state.json").exists()
