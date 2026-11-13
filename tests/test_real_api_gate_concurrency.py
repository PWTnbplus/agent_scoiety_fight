from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from mini_science.authorization import CONFIRMATION_PHRASE, create_authorization
from mini_science.config import load_config
from mini_science.real_gate import GateDenied, PersistentRealGate


def test_real_api_gate_serializes_reservations(tmp_path):
    config = replace(load_config("config/real_gate_v3.json"), allowed_worlds=("W001",), allowed_conditions=("A_TARGET_ONLY",))
    create_authorization(tmp_path, config, approved_by="user_explicit", provider="kimi26", model="kimi-k2.6", scope=["check-api"], worlds=["W001"], conditions=["A_TARGET_ONLY"], max_unique_provider_attempts=1, max_estimated_cost_usd=1.0, confirmation=CONFIRMATION_PHRASE, authorization_note="offline concurrency test")

    def reserve(request_id):
        try:
            gate = PersistentRealGate(tmp_path, config)
            return gate.reserve(request_id=request_id, provider="kimi26", model="kimi-k2.6", stage="check-api", estimated_cost_usd=0.01, world_id="W001", condition="A_TARGET_ONLY").request_id
        except GateDenied:
            return "DENIED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["request-a", "request-b"]))
    assert sorted(results) == ["DENIED", "request-a"] or sorted(results) == ["DENIED", "request-b"]
    assert PersistentRealGate(tmp_path, config).summary()["calls_used"] == 1
