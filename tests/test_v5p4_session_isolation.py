from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from mini_science.authorization import V5P4_CONFIRMATION_PHRASE, create_v5p4_authorization
from mini_science.budget_plan import pilot_request_plan
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, V5P4SessionGate


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan():
    config = load_config("config/v5p4_offline_dev.json")
    return config, pilot_request_plan(".", config, worlds=["CV001"], conditions=list(config.conditions), repeats=1)


def test_v5p4_session_isolated_from_legacy_authorization_and_replay(tmp_path):
    config, plan = _plan()
    legacy_auth = tmp_path / "runs" / "real_authorization_manifest.json"
    legacy_state = tmp_path / "runs" / "v3_real_gate_state.json"
    legacy_auth.parent.mkdir(parents=True)
    legacy_auth.write_text('{"authorization_status":"AUTHORIZED","authorization_id":"legacy"}\n', encoding="utf-8")
    legacy_state.write_text('{"authorization_status":"AUTHORIZED","calls_used":7}\n', encoding="utf-8")
    before = (_sha(legacy_auth), _sha(legacy_state))

    auth_path = create_v5p4_authorization(
        tmp_path,
        config,
        approved_by="user_explicit",
        confirmation=V5P4_CONFIRMATION_PHRASE,
        authorization_note="offline fixture only",
        request_plan=plan,
        worlds=["CV001"],
        conditions=list(config.conditions),
        max_unique_provider_attempts=5,
        max_estimated_cost_usd=0.05,
    )
    session = auth_path.parent
    gate = V5P4SessionGate(tmp_path, session)
    assert gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=plan, worlds=["CV001"], conditions=list(config.conditions))["planned_calls"] == 5

    first = plan[0]
    reservation = gate.reserve(request_id=first["request_id"], provider="kimi26", model="kimi-k2.6", stage=first["stage"], estimated_cost_usd=first["estimated_cost_usd"], world_id="CV001", condition=first["condition"])
    with pytest.raises(GateDenied, match="already attempted"):
        gate.reserve(request_id=first["request_id"], provider="kimi26", model="kimi-k2.6", stage=first["stage"], estimated_cost_usd=first["estimated_cost_usd"], world_id="CV001", condition=first["condition"])
    gate.finish(reservation, status="FAILED", error="offline fixture failure")
    with pytest.raises(GateDenied, match="replay refused"):
        gate.preflight(provider="kimi26", model="kimi-k2.6", request_plan=plan, worlds=["CV001"], conditions=list(config.conditions))
    assert (_sha(legacy_auth), _sha(legacy_state)) == before
    assert (session / "authorization.json").exists()
    assert (session / "gate_state.json").exists()
    assert (session / "planned_requests.jsonl").exists()
    assert (session / "attempt_ledger.jsonl").exists()
    assert json.loads((session / "authorization.json").read_text(encoding="utf-8"))["authorization_status"] == "AUTHORIZED"


def test_v5p4_unknown_billing_stops_session(tmp_path):
    config, plan = _plan()
    auth_path = create_v5p4_authorization(
        tmp_path,
        config,
        approved_by="user_explicit",
        confirmation=V5P4_CONFIRMATION_PHRASE,
        authorization_note="offline fixture only",
        request_plan=plan,
        worlds=["CV001"],
        conditions=list(config.conditions),
        max_unique_provider_attempts=5,
        max_estimated_cost_usd=0.05,
    )
    gate = V5P4SessionGate(tmp_path, auth_path.parent)
    item = plan[0]
    reservation = gate.reserve(request_id=item["request_id"], provider="kimi26", model="kimi-k2.6", stage=item["stage"], estimated_cost_usd=item["estimated_cost_usd"], world_id="CV001", condition=item["condition"])
    gate.finish(reservation, status="UNKNOWN_BILLING_OUTCOME", error="timeout")
    assert gate.summary()["real_api_status"] == "UNKNOWN_BILLING_OUTCOME"
    with pytest.raises(GateDenied, match="UNKNOWN_BILLING_OUTCOME"):
        gate.reserve(request_id=plan[1]["request_id"], provider="kimi26", model="kimi-k2.6", stage=plan[1]["stage"], estimated_cost_usd=plan[1]["estimated_cost_usd"], world_id="CV001", condition=plan[1]["condition"])
