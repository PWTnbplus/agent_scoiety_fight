from __future__ import annotations

from dataclasses import replace

import pytest

from mini_science.authorization import CONFIRMATION_PHRASE, advance_stage, create_authorization
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, PersistentRealGate


def test_real_api_stage_and_world_scope_fail_closed(tmp_path):
    config = replace(load_config("config/real_gate_v3.json"), allowed_worlds=("W001",), allowed_conditions=("A_TARGET_ONLY",))
    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["check-api", "pilot"], worlds=["W001"], conditions=["A_TARGET_ONLY"], max_unique_provider_attempts=8, max_estimated_cost_usd=0.10, confirmation=CONFIRMATION_PHRASE, authorization_note="offline scope test")
    gate = PersistentRealGate(tmp_path, config)
    with pytest.raises(GateDenied):
        gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", worlds=["W001"], conditions=["A_TARGET_ONLY"])
    advance_stage(tmp_path, target_stage="pilot", confirmation=CONFIRMATION_PHRASE)
    gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", worlds=["W001"], conditions=["A_TARGET_ONLY"])
    with pytest.raises(GateDenied):
        gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", worlds=["W002"], conditions=["A_TARGET_ONLY"])
