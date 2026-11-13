from __future__ import annotations

from dataclasses import replace

import pytest

from mini_science.authorization import CONFIRMATION_PHRASE, create_authorization
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, PersistentRealGate
from mini_science.runner import run_pilot


def _authorized_config():
    config = load_config("config/real_gate_v3.json")
    return replace(
        config,
        authorization_status="AUTHORIZED",
        max_unique_calls=1,
        max_estimated_cost_usd=1.0,
        approved_stage="ALL",
    )


def test_v3_persistent_gate_counts_failed_attempts_across_instances(tmp_path):
    config = _authorized_config()
    create_authorization(
        tmp_path,
        config,
        approved_by="user_explicit",
        provider="kimi26",
        model="kimi-k2.6",
        scope=["probe-role"],
        worlds=["W001"],
        conditions=["A_TARGET_ONLY"],
        max_unique_provider_attempts=1,
        max_estimated_cost_usd=1.0,
        confirmation=CONFIRMATION_PHRASE,
        authorization_note="offline test fixture",
    )
    gate = PersistentRealGate(tmp_path, config)
    gate.preflight(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="probe-role", planned_calls=1, planned_cost_usd=0.01, worlds=["W001"])
    reservation = gate.reserve(request_id="probe-1", provider="kimi26", model="kimi-k2.6", stage="probe-role", estimated_cost_usd=0.01, world_id="W001", condition="PROBE")
    gate.finish(reservation, status="FAILED", error="timeout")

    reloaded = PersistentRealGate(tmp_path, config)
    assert reloaded.summary()["calls_used"] == 1
    assert reloaded.load()["attempts"][0]["status"] == "FAILED"
    with pytest.raises(GateDenied):
        reloaded.preflight(provider="kimi26", model="kimi-k2.6", allow_paid_api=True, stage="probe-role", planned_calls=1, planned_cost_usd=0.01, worlds=["W001"])


def test_v3_unauthorized_pilot_stops_before_network(monkeypatch, tmp_path):
    config = load_config("config/real_gate_v3.json")
    called = False

    def no_network(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("mini_science.adapters.kimi26.Kimi26Adapter.complete", no_network)
    with pytest.raises(PermissionError):
        run_pilot(
            tmp_path,
            config,
            provider="kimi26",
            worlds=["W001"],
            conditions=["A_TARGET_ONLY"],
            repeats=1,
            allow_paid_api=True,
            run_dir=tmp_path / "run",
            kimi26_key_file=tmp_path / "missing-key.txt",
        )
    assert called is False

