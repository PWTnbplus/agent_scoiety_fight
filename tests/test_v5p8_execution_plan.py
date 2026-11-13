from __future__ import annotations

from mini_science.authorization import V5P8_CONFIRMATION_PHRASE, create_v5p8_authorization, proposed_v5p8_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.real_gate import V5P8SessionGate


def test_v5p8_plan_has_forty_unique_calls_and_eight_shared_stage1_keys():
    config = load_config("config/v5p8_four_world_two_repeats.json")
    worlds = ["CV001", "CV002", "CV003", "CV004"]
    conditions = list(config.conditions)
    plan = pilot_request_plan(".", config, worlds=worlds, conditions=conditions, repeats=2)
    assert len(plan) == 40
    assert len({item["request_id"] for item in plan}) == 40
    assert sum(item["stage"] == "stage1" for item in plan) == 8
    assert {item["stage1_shared_key"] for item in plan if item["condition"] in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}} == {f"V5P8_{world}_R{rep}" for world in worlds for rep in range(2)}
    proposal = proposed_v5p8_authorization(".", config, request_plan=plan)
    assert proposal["authorization_status"] == "PROPOSED_NOT_AUTHORIZED"
    assert proposal["max_unique_provider_attempts"] == 40
    assert proposal["auto_retry"] is False


def test_v5p8_gate_is_independent_and_preflights_all_forty(tmp_path):
    config = load_config("config/v5p8_four_world_two_repeats.json")
    plan = pilot_request_plan(".", config, worlds=["CV001", "CV002", "CV003", "CV004"], conditions=list(config.conditions), repeats=2)
    authorization_path = create_v5p8_authorization(
        tmp_path,
        config,
        approved_by="user_explicit",
        confirmation=V5P8_CONFIRMATION_PHRASE,
        authorization_note="offline gate fixture",
        request_plan=plan,
        worlds=["CV001", "CV002", "CV003", "CV004"],
        conditions=list(config.conditions),
        max_unique_provider_attempts=40,
        max_estimated_cost_usd=0.40,
    )
    gate = V5P8SessionGate(tmp_path, authorization_path.parent)
    summary = gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=plan, worlds=["CV001", "CV002", "CV003", "CV004"], conditions=list(config.conditions))
    assert summary["planned_calls"] == 40
    assert gate.summary()["calls_remaining"] == 40


def test_v5p8_authorizes_a_bound_cv001_micro_subset(tmp_path):
    config = load_config("config/v5p8_four_world_two_repeats.json")
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(".", config, worlds=["CV001"], conditions=conditions, repeats=1)
    proposal = proposed_v5p8_authorization(
        tmp_path,
        config,
        request_plan=plan,
        worlds=["CV001"],
        conditions=conditions,
        repeats=1,
        max_unique_provider_attempts=5,
        max_estimated_cost_usd=0.05,
    )
    assert len(plan) == 5
    assert proposal["worlds"] == ["CV001"]
    assert proposal["repeats"] == 1
    assert proposal["max_unique_provider_attempts"] == 5
    assert proposal["max_estimated_cost_usd"] == 0.05

    authorization_path = create_v5p8_authorization(
        tmp_path,
        config,
        approved_by="user_explicit",
        confirmation=V5P8_CONFIRMATION_PHRASE,
        authorization_note="offline micro subset fixture",
        request_plan=plan,
        worlds=["CV001"],
        conditions=conditions,
        repeats=1,
        max_unique_provider_attempts=5,
        max_estimated_cost_usd=0.05,
    )
    gate = V5P8SessionGate(tmp_path, authorization_path.parent)
    result = gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=plan, worlds=["CV001"], conditions=conditions)
    assert result["planned_calls"] == 5
    assert result["cost_remaining"] > 0


def test_unexecuted_rows_are_not_action_valid():
    from mini_science.analysis import _action_valid

    row = {"run_status": "FAILED", "experiment_id_selected": "", "selected_action": "", "action_valid": "True", "valid": "False"}
    assert _action_valid(row) is False
