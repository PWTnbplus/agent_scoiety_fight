from __future__ import annotations

from mini_science.authorization import proposed_v5p11_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config


def test_v5p12_remainder_proposal_is_exactly_six_blocks_and_thirty_requests():
    config = load_config("config/v5p11_main.json")
    worlds = ["IV002", "IV003", "IV004"]
    conditions = ["A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"]
    plan = pilot_request_plan(".", config, worlds=worlds, conditions=conditions, repeats=2, request_namespace="V5P12REMTEST", input_rate=0.00095, output_rate=0.004)
    proposal = proposed_v5p11_authorization(".", config, request_plan=plan, worlds=worlds, conditions=conditions, repeats=2, request_namespace="V5P12REMTEST", max_unique_provider_attempts=30, max_estimated_cost_usd=0.25)
    assert len(plan) == 30
    assert len({row["request_id"] for row in plan}) == 30
    assert proposal["protocol_variant"] == "v5p12_remainder"
    assert proposal["max_unique_provider_attempts"] == 30
    assert proposal["worlds"] == worlds
    assert sum(row["stage"] == "stage1" for row in plan) == 6
