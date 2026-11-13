from __future__ import annotations

from dataclasses import replace

import pytest

from mini_science.authorization import CONFIRMATION_PHRASE, advance_stage, create_authorization
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, PersistentRealGate


def _config():
    return replace(load_config("config/real_gate_v3.json"), allowed_worlds=("W001",), allowed_conditions=("A_TARGET_ONLY", "B_SINGLE_RELATED", "C_SEQ2_TRANSFER", "D_SEQ2_BLOCK"))


def test_real_api_requires_explicit_manifest_and_stage_advance(tmp_path):
    config = _config()
    gate = PersistentRealGate(tmp_path, config)
    with pytest.raises(GateDenied):
        gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="check-api", worlds=["W001"])

    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["check-api", "probe-role", "pilot"], worlds=["W001"], conditions=list(config.allowed_conditions), max_unique_provider_attempts=8, max_estimated_cost_usd=0.10, confirmation=CONFIRMATION_PHRASE, authorization_note="offline test")
    gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="check-api", worlds=["W001"])
    with pytest.raises(GateDenied):
        gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="pilot", worlds=["W001"])

    advance_stage(tmp_path, target_stage="probe-role", confirmation=CONFIRMATION_PHRASE)
    gate.assert_authorized(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="probe-role", worlds=["W001"])
    with pytest.raises(PermissionError):
        advance_stage(tmp_path, target_stage="check-api", confirmation=CONFIRMATION_PHRASE)


def test_real_api_authorization_cannot_be_overwritten_or_self_confirmed(tmp_path):
    config = _config()
    with pytest.raises(PermissionError):
        create_authorization(tmp_path, config, approved_by="codex", provider="kimi26", model="kimi-k2.6", scope=["check-api"], worlds=["W001"], conditions=["A_TARGET_ONLY"], max_unique_provider_attempts=1, max_estimated_cost_usd=0.01, confirmation=CONFIRMATION_PHRASE, authorization_note="invalid")
    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["check-api"], worlds=["W001"], conditions=["A_TARGET_ONLY"], max_unique_provider_attempts=1, max_estimated_cost_usd=0.01, confirmation=CONFIRMATION_PHRASE, authorization_note="offline test")
    with pytest.raises(PermissionError):
        create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["check-api"], worlds=["W001"], conditions=["A_TARGET_ONLY"], max_unique_provider_attempts=1, max_estimated_cost_usd=0.01, confirmation=CONFIRMATION_PHRASE, authorization_note="overwrite")
