from __future__ import annotations

from dataclasses import replace

from mini_science.authorization import CONFIRMATION_PHRASE, create_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.real_gate import PersistentRealGate


def test_real_api_budget_is_an_upper_bound_not_a_local_underestimate(tmp_path):
    config = replace(load_config("config/real_gate_v3.json"), allowed_worlds=("W001",), allowed_conditions=("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"))
    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["pilot"], worlds=["W001"], conditions=list(config.allowed_conditions), max_unique_provider_attempts=8, max_estimated_cost_usd=0.10, confirmation=CONFIRMATION_PHRASE, authorization_note="offline budget test")
    plan = pilot_request_plan(".", config, worlds=["W001"], conditions=list(config.allowed_conditions), repeats=1)
    assert sum(row["estimated_cost_usd"] for row in plan) > 0
    gate = PersistentRealGate(tmp_path, config, run_max_calls=8, run_max_cost_usd=sum(row["estimated_cost_usd"] for row in plan) - 1e-9)
    try:
        gate.preflight(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", request_plan=plan, worlds=["W001"], conditions=list(config.allowed_conditions))
    except PermissionError:
        pass
    else:
        raise AssertionError("under-cap preflight must reject before transport")
