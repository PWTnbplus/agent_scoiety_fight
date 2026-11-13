from __future__ import annotations

from mini_science.authorization import proposed_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config


def test_v5p4_frozen_five_request_plan_has_exact_stage_output_caps():
    config = load_config("config/v5p4_offline_dev.json")
    plan = pilot_request_plan(".", config, worlds=["CV001"], conditions=list(config.conditions), repeats=1)
    assert len(plan) == 5
    assert len({item["request_id"] for item in plan}) == 5
    by_stage = {item["stage"]: [] for item in plan}
    for item in plan:
        by_stage.setdefault(item["stage"], []).append(item)
    assert [item["max_output_tokens"] for item in by_stage["stage2"] if item["condition"] in {"A_TARGET_ONLY", "B_SINGLE_RELATED"}] == [900, 900]
    assert [item["max_output_tokens"] for item in by_stage["stage1"]] == [600]
    assert [item["max_output_tokens"] for item in by_stage["stage2"] if item["condition"] in {"C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"}] == [600, 600]
    assert sum(float(item["estimated_cost_usd"]) for item in plan) < 0.05
    proposal = proposed_v5p4_authorization(".", config, request_plan=plan)
    assert proposal["authorization_status"] == "PROPOSED_NOT_AUTHORIZED"
    assert proposal["real_api_calls_this_round"] == 0
    assert proposal["request_plan_hash"]
    assert set(proposal["prompt_hashes"]) == {item["request_id"] for item in plan}
    assert proposal["max_output_tokens_by_stage"] == {"stage2_single": 900, "stage1": 600, "stage2_seq2": 600}
